"""Public family construction and read-only verification entry points."""
import argparse
import json
from pathlib import Path
from .core import generate, verify


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='command', required=True)
    g = sub.add_parser('generate'); g.add_argument('--input', type=Path, required=True); g.add_argument('--out', type=Path, required=True)
    v = sub.add_parser('verify'); v.add_argument('folder', type=Path)
    c = sub.add_parser('connect'); c.add_argument('--families', type=Path, required=True); c.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.command == 'generate':
        result = generate(a.input, a.out)
    elif a.command == 'verify':
        result = verify(a.folder)
    else:
        from .connect import connect
        result = connect(a.families, a.out)
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
