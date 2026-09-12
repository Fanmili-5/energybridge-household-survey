"""Synthetic fixtures for the regional human-intake contract, never real participants."""
from verify_paired_physics import answers as legacy_answers


def answers(**changes):
    raw=legacy_answers()
    raw.update(X_REGION='广东',X_CITY='广州',X_BUILDING='apartment',X_AREA='90_119',
               X_AREA_BASIS='usable',X_FLOOR='middle')
    raw.update(changes)
    return raw
