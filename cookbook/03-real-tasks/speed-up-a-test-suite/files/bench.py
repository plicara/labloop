"""Time the test suite, and refuse to be fooled by a smaller one. Protected.

Hashing `tests/` would be the obvious protection and it is the wrong one:
almost all of this suite's slowness lives *in* the tests -- a fixture with the
wrong scope, a real sleep in a retry test -- so an agent that cannot edit them
cannot do the task at all.

What must not change is not the text of the tests but **what the run proves**.
So this file asserts a property of the run instead:

  - every test that existed still runs (EXPECTED_TESTS), and
  - all of them pass, and
  - a separate acceptance check, which the agent cannot edit, still passes.

The count is what stops the classic cheat: deleting or skipping the slow tests
is the fastest way to make any suite fast.
"""

import re
import subprocess
import sys
import time

EXPECTED_TESTS = 53


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    start = time.perf_counter()
    proc = run([sys.executable, "-m", "pytest", "-q", "tests", "-p", "no:cacheprovider"])
    elapsed = time.perf_counter() - start

    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        sys.exit(f"suite did not pass:\n{out[-1500:]}")

    m = re.search(r"(\d+) passed", out)
    if not m:
        sys.exit(f"could not read a pass count from pytest:\n{out[-1500:]}")
    passed = int(m.group(1))

    if passed != EXPECTED_TESTS:
        sys.exit(
            f"expected {EXPECTED_TESTS} passing tests, got {passed}. "
            "Making the suite smaller is not making it faster."
        )

    for marker in ("skipped", "xfailed", "deselected"):
        if marker in out:
            sys.exit(f"tests were {marker}; every test must actually run:\n{out[-500:]}")

    # The unit tests can be rewritten; this cannot. If the suite were gutted
    # while still reporting 55 passes, this is what would still catch it.
    acc = run([sys.executable, "acceptance_test.py"])
    if acc.returncode != 0:
        sys.exit(f"acceptance check failed:\n{acc.stdout[-800:]}{acc.stderr[-800:]}")

    print(f"seconds = {elapsed:.4f}")


if __name__ == "__main__":
    main()
