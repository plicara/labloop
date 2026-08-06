"""The corpus: the Python standard library's own source, whatever is installed.

Real files, real size (~4.7 MB across ~170 modules on CPython 3.12), and
present on any machine that can run this recipe. Nothing to download.
"""

import glob
import os
import sysconfig


def files():
    """Return the stdlib .py files, sorted, so every run sees the same corpus."""
    stdlib = sysconfig.get_paths()["stdlib"]
    found = sorted(glob.glob(os.path.join(stdlib, "*.py")))
    if len(found) < 50:
        raise SystemExit(f"expected a stdlib full of .py files, found {len(found)} in {stdlib}")
    return found
