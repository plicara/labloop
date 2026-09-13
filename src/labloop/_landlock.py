"""Linux Landlock confinement: read everywhere, write only the worktree.

This is labloop's dependency-free Linux fallback, run as

    python -m labloop._landlock <worktree> -- <command...>

It applies a Landlock ruleset to itself and then `exec`s the command, so the
confinement cannot be escaped by the command or any child it spawns (Landlock is
inherited across fork/execve).

Why a ruleset and not a namespace: Landlock is unprivileged and needs no user
namespaces, which are frequently disabled (Ubuntu's
`kernel.apparmor_restrict_unprivileged_userns`). A namespace-based tool
(bubblewrap, nsjail) is preferred where it works — see `sandbox.py` — but this
is the fallback that works on any kernel with Landlock.

The approach mirrors the landrun project (github.com/Zouuup/landrun): grant
read+execute beneath `/`, grant everything beneath the worktree, set
`NO_NEW_PRIVS`, restrict self. It fails **closed**: any step that cannot be
applied prints to stderr and exits without running the command, so a kernel
without Landlock can never silently run unconfined.

What it does not do: reads are open, network is untouched, and a write via a
file descriptor opened before this process started is not revoked. See the
sandbox section of the docs.
"""
from __future__ import annotations

import ctypes
import os
import struct
import sys

# x86_64 syscall numbers; other architectures differ and are rejected below.
_NR_CREATE, _NR_ADD, _NR_RESTRICT = 444, 445, 446
_PR_SET_NO_NEW_PRIVS = 38
_VERSION_FLAG = 1 << 0
_RULE_PATH_BENEATH = 1

# Filesystem access rights (linux/landlock.h).
_EXECUTE, _WRITE_FILE, _READ_FILE, _READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
_REMOVE_DIR, _REMOVE_FILE = 1 << 4, 1 << 5
_MAKE_CHAR, _MAKE_DIR, _MAKE_REG = 1 << 6, 1 << 7, 1 << 8
_MAKE_SOCK, _MAKE_FIFO, _MAKE_BLOCK, _MAKE_SYM = 1 << 9, 1 << 10, 1 << 11, 1 << 12
_REFER, _TRUNCATE, _IOCTL_DEV = 1 << 13, 1 << 14, 1 << 15


def _libc() -> ctypes.CDLL:
    try:
        return ctypes.CDLL("libc.so.6", use_errno=True)
    except OSError:  # pragma: no cover - non-glibc Linux
        return ctypes.CDLL(None, use_errno=True)


class _RulesetAttr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


def _die(message: str, code: int = 127) -> None:
    print(f"labloop._landlock: {message}", file=sys.stderr)
    raise SystemExit(code)


def _handled_access(abi: int) -> int:
    handled = (
        _EXECUTE | _WRITE_FILE | _READ_FILE | _READ_DIR | _REMOVE_DIR | _REMOVE_FILE
        | _MAKE_CHAR | _MAKE_DIR | _MAKE_REG | _MAKE_SOCK | _MAKE_FIFO | _MAKE_BLOCK
        | _MAKE_SYM
    )
    if abi >= 2:
        handled |= _REFER
    if abi >= 3:
        handled |= _TRUNCATE
    if abi >= 5:
        handled |= _IOCTL_DEV
    return handled


def confine(worktree: str, argv: list[str]) -> None:
    """Apply Landlock (write only beneath `worktree`) and exec `argv`."""
    libc = _libc()
    syscall = libc.syscall
    syscall.restype = ctypes.c_long

    def call(number: int, *args: object) -> tuple[int, int]:
        ctypes.set_errno(0)
        result = syscall(ctypes.c_long(number), *args)
        return int(result), ctypes.get_errno()

    abi, err = call(_NR_CREATE, None, ctypes.c_size_t(0), ctypes.c_int(_VERSION_FLAG))
    if abi < 1:
        _die(f"Landlock unavailable (abi probe errno={err}); refusing to run unconfined")

    # Scratch inside the worktree: without this, tools that write to $TMPDIR
    # would be (correctly) denied, and pointing TMPDIR at the real /tmp would
    # reopen the bytecode-mirror hole this sandbox exists to close.
    scratch = os.path.join(worktree, ".labloop-tmp")
    os.makedirs(scratch, exist_ok=True)
    os.environ["TMPDIR"] = os.environ["TMP"] = os.environ["TEMP"] = scratch

    handled = _handled_access(abi)
    attr = _RulesetAttr(handled, 0, 0)
    ruleset_fd, err = -1, 0
    for size in (24, 16, 8):  # shrink for kernels whose attr is smaller
        ruleset_fd, err = call(_NR_CREATE, ctypes.byref(attr), ctypes.c_size_t(size),
                               ctypes.c_int(0))
        if ruleset_fd >= 0:
            break
        if err != 7:  # E2BIG: only then is a smaller attr the fix
            break
    if ruleset_fd < 0:
        _die(f"landlock_create_ruleset failed errno={err}; refusing to run unconfined")

    read_only = _EXECUTE | _READ_FILE | _READ_DIR
    if abi >= 2:
        read_only |= _REFER
    if abi >= 5:
        read_only |= _IOCTL_DEV
    root_fd = os.open("/", os.O_PATH | os.O_CLOEXEC)
    tree_fd = os.open(worktree, os.O_PATH | os.O_CLOEXEC)
    try:
        for fd, allowed in ((root_fd, read_only), (tree_fd, handled)):
            rule = ctypes.create_string_buffer(struct.pack("<Q", allowed) + struct.pack("<i", fd))
            result, err = call(_NR_ADD, ctypes.c_int(ruleset_fd),
                               ctypes.c_int(_RULE_PATH_BENEATH), rule, ctypes.c_int(0))
            if result != 0:
                _die(f"landlock_add_rule failed errno={err}; refusing to run unconfined")
    finally:
        os.close(root_fd)
        os.close(tree_fd)

    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        _die("prctl(PR_SET_NO_NEW_PRIVS) failed; refusing to run unconfined")
    result, err = call(_NR_RESTRICT, ctypes.c_int(ruleset_fd), ctypes.c_int(0))
    os.close(ruleset_fd)
    if result != 0:
        _die(f"landlock_restrict_self failed errno={err}; refusing to run unconfined")

    os.execvp(argv[0], argv)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3 or args[1] != "--":
        _die("usage: python -m labloop._landlock <worktree> -- <command...>", 2)
    worktree = os.path.realpath(args[0])
    if not os.path.isdir(worktree):
        _die(f"worktree is not a directory: {worktree}", 2)
    confine(worktree, args[2:])


if __name__ == "__main__":
    main()
