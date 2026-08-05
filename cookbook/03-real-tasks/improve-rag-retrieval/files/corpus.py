"""The corpus: one document per Python standard-library module.

Each document is what a documentation chunk usually looks like -- a title, a
prose summary, and the names it defines. Real text, and a real vocabulary
mismatch between how documentation is written and how people ask questions.

Built by importing, not by parsing source, so that C modules (`itertools`,
`decimal`, `zlib`) are present too. A corpus that silently omitted them would
make the queries about them unanswerable and the scores meaningless.
"""

import importlib
import pkgutil
import sys
import warnings

# Importing is the price of covering C modules. These are the ones where the
# import itself is the problem: it opens a browser, starts a UI, prints, or
# costs seconds.
DENY = {
    "antigravity", "this", "idlelib", "tkinter", "turtle", "turtledemo",
    "ensurepip", "lib2to3", "pydoc_data", "test", "distutils", "venv",
    "__hello__", "__phello__", "curses", "dbm", "crypt", "nis", "ossaudiodev",
    "spwd", "msilib", "winreg", "winsound", "msvcrt",
}


def _document(name):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            mod = importlib.import_module(name)
        except BaseException:  # noqa: BLE001 - any import failure just skips
            return None

    doc = (getattr(mod, "__doc__", "") or "").strip()
    names = [n for n in dir(mod) if not n.startswith("_")]

    # Submodule names matter: someone asking about "urllib" wants to see that
    # `request` and `parse` live there, and the package docstring rarely says.
    subs = []
    if hasattr(mod, "__path__"):
        try:
            subs = [
                m.name
                for m in pkgutil.iter_modules(mod.__path__)
                if not m.name.startswith("_")
            ]
        except Exception:  # noqa: BLE001
            subs = []

    if not doc and not names:
        return None
    return {"id": name, "title": name, "summary": doc, "names": names, "submodules": subs}


def documents():
    """Every importable top-level stdlib module, as a retrievable document."""
    docs = []
    for name in sorted(sys.stdlib_module_names):
        if name.startswith("_") or name in DENY:
            continue
        d = _document(name)
        if d:
            docs.append(d)
    if len(docs) < 100:
        raise SystemExit(f"expected a full stdlib, built only {len(docs)} documents")
    return docs
