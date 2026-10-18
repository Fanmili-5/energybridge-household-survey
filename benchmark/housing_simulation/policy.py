"""Versioned reference parameters, with epistemic classification beside values."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

POLICY = Path(__file__).with_name('ASSUMPTIONS.json')


@lru_cache(maxsize=1)
def entries():
    return {e['id']: e for e in json.loads(POLICY.read_text())['entries']}


def reference(name):
    return entries()[name]['values']


def fingerprint():
    return hashlib.sha256(POLICY.read_bytes()).hexdigest()
