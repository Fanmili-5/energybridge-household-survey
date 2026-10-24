"""Versioned household portrait mapping over the unchanged Gaussian sampler.

v1 replays its byte-preserved implementation and original provenance. v2
changes preference meanings, not the latent random stream or A/B algorithms.
"""
import copy
import math

from .core import HERE, digest, read, require, sha
from . import joint_sampling_v1 as legacy

VERSION = legacy.VERSION
VERSION2 = 'within_class_joint_v2'
RULES = legacy.RULES
V2_RULES = HERE / 'JOINT_SAMPLING_RULES_V2.json'
normal = legacy.normal
coordinates = legacy.coordinates
quantile = legacy.quantile
feasible_starts = legacy.feasible_starts
clock = legacy.clock


def rules_path(mode):
    return V2_RULES if mode == VERSION2 else RULES


def method_hash(mode):
    if mode == VERSION:
        return sha(HERE / 'joint_sampling_v1.py')
    return digest({p: sha(HERE/p) for p in ('joint_sampling.py', 'joint_sampling_v1.py', 'portrait_v2.py')})


def configuration(value):
    require(isinstance(value, dict) and set(value) <= {'mode', 'seed', 'loading'}, 'JOINT_UNKNOWN_CONFIGURATION')
    mode = value.get('mode')
    require(mode in (VERSION, VERSION2) and type(value.get('seed')) is int, 'JOINT_MODE_OR_SEED_REQUIRED')
    loading = value.get('loading', read(rules_path(mode))['loading_default'])
    require(type(loading) in (int, float) and math.isfinite(loading) and 0 <= loading <= 1, 'JOINT_INVALID_LOADING')
    return {'mode': mode, 'seed': value['seed'], 'loading': loading}


def sample(source, role_rules, cfg):
    cfg = configuration(cfg)
    if cfg['mode'] == VERSION2:
        from .portrait_v2 import sample as sample_v2
        return sample_v2(source, role_rules, cfg)
    result = legacy.sample(source, role_rules, cfg)
    # The archived sampler executed. Restore its original filename provenance.
    result['code_sha256'] = method_hash(VERSION)
    result['profile_sha256'] = digest({k:v for k,v in result.items() if k != 'profile_sha256'})
    return result


def check_frozen(joint):
    cfg = configuration(joint['configuration'])
    require(joint['profile_sha256'] == digest({k:v for k,v in joint.items() if k != 'profile_sha256'}), 'JOINT_FROZEN_HASH_MISMATCH')
    require(joint['rules_sha256'] == sha(rules_path(cfg['mode'])) and joint['code_sha256'] == method_hash(cfg['mode']), 'JOINT_FROZEN_METHOD_CHANGED')


def obtain(source, role_rules):
    cfg = source.get('energy_preferences', {}).get('preference_sampling')
    if cfg is None:
        return None
    cfg = configuration(cfg)
    frozen = source.get('frozen_joint_sampling')
    if frozen is None:
        return sample(source, role_rules, cfg)
    check_frozen(frozen)
    require(frozen['household_id'] == source['household_id'] and frozen['role'] == source['role'] and frozen['configuration'] == cfg, 'JOINT_FROZEN_IDENTITY_MISMATCH')
    require({(r['asset_id'],r['kind']) for r in frozen['devices']} == {(d['asset_id'],k) for d in source['devices'] for k in d['types']}, 'JOINT_FROZEN_DEVICE_SET_CHANGED')
    return copy.deepcopy(frozen)


def apply_to_life(life, profile):
    """Family-side adapter only; the original A/B algorithms remain untouched."""
    joint = profile.get('joint_sampling')
    if joint is None:
        return copy.deepcopy(life), []
    check_frozen(joint)
    if joint['version'] == VERSION2:
        from .portrait_v2 import apply_to_life as apply_v2
        return apply_v2(life, profile)
    # v1 checks a historic fixed filename; adapt a copy only after validating
    # the original frozen profile against the actual byte-preserved sampler.
    adapted = copy.deepcopy(profile)
    adapted['joint_sampling']['code_sha256'] = sha(HERE/'joint_sampling.py')
    adapted['joint_sampling']['profile_sha256'] = digest({k:v for k,v in adapted['joint_sampling'].items() if k != 'profile_sha256'})
    return legacy.apply_to_life(life, adapted)


def attach(profile, joint):
    if joint is not None and joint['version'] == VERSION2:
        from .portrait_v2 import attach as attach_v2
        return attach_v2(profile, joint)
    return legacy.attach(profile, joint)


def render(profile):
    if profile['joint_sampling']['version'] == VERSION2:
        from .portrait_v2 import render as render_v2
        return render_v2(profile)
    return legacy.render(profile)
