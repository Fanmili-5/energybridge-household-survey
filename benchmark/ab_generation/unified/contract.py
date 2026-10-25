"""Versioned experimental settings, independent random streams and provenance."""
import copy
import datetime as dt
import math
from pathlib import Path
from ..common import digest, sha

DEFAULT = dict(schema='eb.unified_generation.v1', method_revision='delivery_v2_3', seed=20261022,
    event=dict(event_id='fixed-vpp-18-19', start_min=1080, end_min=1140,
               direction='down', target_kw=None),
    step_min=10, rows_per_unit=256, queries_per_row=16,search_strategy='ipog_c',
    oracle_deterministic_time=0.05, A_deterministic_time=20.0, A_target_context_mode='frozen_v3',
    oracle_native_encoding_budget=4096,
    oracle_propagation='none', oracle_forward_node_budget=1024,
    mechanism_joint_extension=False, opportunity_bounds='none',
    handling_calendar_domain='convenience_only',
    selection_nodes=2000, block_households=50, selection_joint_order='legacy_buckets_v1',
    ac_delta_C=[0.5, 1.0, 2.0], tank_delta_C=[1.0, 3.0, 5.0],
    thermal_duration_min=[10, 20, 30, 40, 50, 60],
    precondition_min=[10, 20, 30, 40, 50, 60],
    relative_cuts=[1/3, 2/3], repeat_family=0.25,
    repeat_composition=0.5, repeat_context=1.0)


def config(value=None):
    value = value or {}
    if set(value)-set(DEFAULT): raise ValueError('UNKNOWN_UNIFIED_CONFIGURATION')
    c = {**copy.deepcopy(DEFAULT), **copy.deepcopy(value)}
    # 2.1 non-granular routes remain source-compatible. Exact historical code
    # replay uses its frozen source archive, not this patched implementation.
    if c['method_revision'] not in ('delivery_v2_1','delivery_v2_2','delivery_v2_3','delivery_v2_5','delivery_v2_6','delivery_v2_7','delivery_v2_8','delivery_v2_9','delivery_v2_10','delivery_v2_11'):raise ValueError('REPLAY_OLDER_METHOD_FROM_PINNED_SOURCE_SNAPSHOT')
    if c['selection_joint_order'] not in ('legacy_buckets_v1','exact_witnessed_v1'):
        raise ValueError('UNKNOWN_JOINT_ORDER_SELECTION_POLICY')
    if c['selection_joint_order']=='exact_witnessed_v1' and c['method_revision'] not in ('delivery_v2_10','delivery_v2_11'):
        raise ValueError('NEW_SELECTION_POLICY_REQUIRES_NEW_REVISION')
    e = c['event']
    if (c['schema'] != DEFAULT['schema'] or c['step_min'] != 10 or
        e.get('start_min') != 1080 or e.get('end_min') != 1140 or
        e.get('direction') != 'down' or set(e) != set(DEFAULT['event'])):
        raise ValueError('UNIFIED_REQUIRES_FIXED_18_19_EVENT')
    if e['target_kw'] is not None and (type(e['target_kw']) not in (int,float) or
        not math.isfinite(e['target_kw']) or e['target_kw'] <= 0):
        raise ValueError('INVALID_DECLARED_EVENT_TARGET')
    for k in ('rows_per_unit','queries_per_row','selection_nodes','block_households','oracle_native_encoding_budget','oracle_forward_node_budget'):
        if type(c[k]) is not int or c[k] <= 0: raise ValueError('INVALID_BUDGET:'+k)
    if type(c['seed']) is not int: raise ValueError('INVALID_SEED')
    if c['search_strategy'] not in ('ipog_c','legacy_round_robin_adapter'):raise ValueError('UNKNOWN_SEARCH_STRATEGY')
    if c['A_target_context_mode'] not in ('frozen_v3','life_conditional_v1'):raise ValueError('UNKNOWN_A_TARGET_CONTEXT_MODE')
    if type(c['mechanism_joint_extension']) is not bool:raise ValueError('INVALID_MECHANISM_EXTENSION_MODE')
    if c['opportunity_bounds'] not in ('none','precedence_v1'):raise ValueError('UNKNOWN_OPPORTUNITY_BOUND_MODE')
    if c['handling_calendar_domain'] not in ('convenience_only','include_life_conflicts'):raise ValueError('UNKNOWN_HANDLING_CALENDAR_DOMAIN')
    if c['oracle_propagation'] not in ('none','interval_v1','interval_forward_v1'):raise ValueError('UNKNOWN_ORACLE_PROPAGATION')
    for k in ('A_deterministic_time','oracle_deterministic_time'):
        if type(c[k]) not in (int,float) or not math.isfinite(c[k]) or c[k] <= 0:
            raise ValueError('INVALID_TIME_BUDGET')
    for k in ('ac_delta_C','tank_delta_C','thermal_duration_min','precondition_min'):
        if not c[k] or any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in c[k]):
            raise ValueError('INVALID_NATIVE_AXIS:'+k)
        if c[k] != sorted(set(c[k])): raise ValueError('UNORDERED_NATIVE_AXIS')
    if any(x % 10 or x > 60 for k in ('thermal_duration_min','precondition_min') for x in c[k]):
        raise ValueError('INVALID_NATIVE_DURATION')
    if len(c['relative_cuts']) != 2 or not 0<c['relative_cuts'][0]<c['relative_cuts'][1]<1:
        raise ValueError('INVALID_RELATIVE_CUTS')
    for k in ('repeat_family','repeat_composition','repeat_context'):
        if type(c[k]) not in (int,float) or not math.isfinite(c[k]) or c[k]<0:
            raise ValueError('INVALID_REPEAT_WEIGHT')
    return c


def entry_config(path=None):
    """The CLI uses the current method; explicit files retain their own mode.

    Internal config(None) keeps the legacy API default. Historical byte replay
    still requires its recorded source snapshot, not this revised runtime.
    """
    from ..common import read
    return config(read(Path(path) if path else Path(__file__).with_name('CURRENT_CONFIG.json')))


def stream(seed, stage, *identity):
    return int(digest([seed, stage, *identity])[:8],16) % (2**31-1)


def dates(available, seed, household, given=None):
    available = sorted(set(available))
    for d in available: dt.date.fromisoformat(d)
    chosen = list(given) if given is not None else sorted(
        sorted(available,key=lambda d:digest([seed,'dates',household,d]))[:10])
    if len(chosen)!=10 or len(set(chosen))!=10 or not set(chosen)<=set(available):
        raise ValueError('TEN_DISTINCT_SUPPORTED_DATES_REQUIRED')
    return chosen


def code_hash():
    here=Path(__file__).parent
    own={p.name:sha(p) for p in sorted(here.glob('*')) if p.suffix in ('.py','.json')}
    # Imported legacy adapters are part of the method, not an untracked dependency.
    legacy={p.name:sha(p) for p in sorted(here.parent.glob('*.py'))}
    production=here.parents[1]/'research_delivery/production.py'
    return digest({'unified':own,'legacy_adapters':legacy,'production_orchestrator':sha(production)})


def bind(A, B, context, portrait=None):
    return dict(A_sha256=digest(A), B_sha256=digest(B),
                context_sha256=digest(context), portrait_sha256=digest(portrait),
                physical_outcomes=None, human_acceptance=None, human_score=None,
                human_reason=None, simulation_status='not_computed')
