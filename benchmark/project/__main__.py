"""Connect the three generators to the existing v69 form; never run EP."""
import argparse
import json
from pathlib import Path
from .pipeline import DEFAULT_INPUT, build, check


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('build'); a.add_argument('--input', type=Path, default=DEFAULT_INPUT); a.add_argument('--out', type=Path, required=True)
    a = sub.add_parser('verify'); a.add_argument('folder', type=Path)
    a = sub.add_parser('prepare-idf'); a.add_argument('--project', type=Path, required=True); a.add_argument('--weather', type=Path, required=True); a.add_argument('--out', type=Path, required=True); a.add_argument('--sample-id', action='append'); a.add_argument('--preparation-profile', type=Path)
    a = sub.add_parser('questionnaire'); a.add_argument('--project', type=Path, required=True); a.add_argument('--out', type=Path, required=True)
    a = sub.add_parser('verify-questionnaire'); a.add_argument('folder', type=Path)
    a = sub.add_parser('serve'); a.add_argument('--release', type=Path, default=Path(__file__).parent / 'examples/questionnaire'); a.add_argument('--port', type=int, default=18780)
    args = p.parse_args()
    if args.command == 'build': result = build(args.input, args.out)
    elif args.command == 'verify': result = check(args.folder)
    elif args.command == 'prepare-idf':
        from .prepare import prepare
        result = prepare(args.project, args.weather, args.out, args.sample_id, profile=args.preparation_profile)
    elif args.command == 'questionnaire':
        from .questionnaire import build_questionnaire
        result = build_questionnaire(args.project, args.out)
    elif args.command == 'verify-questionnaire':
        from .questionnaire import verify_questionnaire
        result = verify_questionnaire(args.folder)
    else:
        from .server import serve
        return serve(args.release, args.port)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
