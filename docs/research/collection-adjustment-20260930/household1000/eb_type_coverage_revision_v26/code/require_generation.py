#!/usr/bin/env python3
"""Hold production pending concrete EB-type coverage and original50 acceptance.

Real national preference prevalence is not an admission requirement. No JSON
flag can replace missing content-bound semantic,coverage and physical checks.
"""
import json
import sys


def require_generation():
    raise RuntimeError(
        'EB type coverage hold: concrete household-policy-to-routine/service/'
        'A-B/IDF propagation, label-blind feature extraction and original50 '
        'coverage acceptance are not implemented. Freeze the type-coverage '
        'design and content-bound validation before new production. National '
        'preference prevalence is not a prerequisite; assigned-actor counts '
        'and historical V23/V24/V25 checks cannot authorize generation or EP.'
    )


if __name__ == '__main__':
    try:
        require_generation()
    except RuntimeError as exc:
        print(json.dumps({'generation_allowed': False, 'EP_allowed': False,
                          'objective': 'type_coverage_consistent_with_EB',
                          'real_prevalence_is_generation_prerequisite': False,
                          'reason': str(exc)}, ensure_ascii=False))
        sys.exit(2)
