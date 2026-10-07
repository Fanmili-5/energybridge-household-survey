"""Fail before any write to a sealed research package."""
from pathlib import Path
def ensure_unsealed(folder):
    if (Path(folder)/'PACKAGE_MANIFEST.json').exists():
        raise SystemExit('Sealed research package: no mutation. Reproduce in a new copy; useaudit_manifest.py for read-only checks.')
