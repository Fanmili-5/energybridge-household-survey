#!/usr/bin/env python3
"""Hold generation until population grounding and coherent EB6 recovery exist.

This revision intentionally provides no acceptance-switch implementation.
Neither a historical acceptance nor editing JSON flags can authorize production.
"""
import json
import sys


def require_generation():
    raise RuntimeError(
        'Population grounding hold: real Chinese-city household EB6 shares are '
        'not identified. Freeze independently measured preferences, household '
        'weights, validated six-type mapping and uncertainty before quotas; '
        'then verify coherent original50 recovery. Assigned-role counts and '
        'historical V23/V24 checks cannot authorize generation or EP.'
    )


if __name__ == '__main__':
    try:
        require_generation()
    except RuntimeError as exc:
        print(json.dumps({'generation_allowed': False, 'EP_allowed': False,
                          'reason': str(exc)}, ensure_ascii=False))
        sys.exit(2)
