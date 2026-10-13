#!/usr/bin/env python3
"""Hold production while the EB-six-type prerequisite is being implemented.

No legacy acceptance, structural max-flow allocation, label-only assignment,
or fabricated cluster result can satisfy this prerequisite. A later revision
must replace this hold with actual content-bound blueprint/recovery acceptance.
"""
import json
from pathlib import Path
import sys

STAGE = Path(__file__).resolve().parents[1]


def require_generation():
    requirement = json.loads((STAGE / 'REQUIREMENT.json').read_text())
    if requirement['user_confirmed_quota_origin'] != 'EB_published_assigned_persona_mix':
        raise RuntimeError('EB six-type hold: quota origin must be re-resolved')
    raise RuntimeError('EB six-type hold: the v24 prerequisite is not accepted. '
                       'Reconcile eligible household units, implement coherent policy blueprints, '
                       'and verify blind recovery on original50 before generation. '
                       'V23 acceptance does not meet this new requirement.')


if __name__ == '__main__':
    try:
        require_generation()
    except (RuntimeError, KeyError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(json.dumps({'generation_allowed': False, 'EP_allowed': False,
                          'reason': str(exc)}, ensure_ascii=False))
        sys.exit(2)
