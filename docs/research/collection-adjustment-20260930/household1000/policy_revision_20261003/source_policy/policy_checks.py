"""Independent policy checks; no generator/core import and no survey-row access.

This policy checker is a review aid, not the runtime geometry or source gate.
Its envelope is deliberately independent from frozen profile schemas.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import datetime

VERSION = 'eb.source_housing_policy.checks.v1'

def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        return False
    if isinstance(value, dict):
        return all(finite_tree(v) for v in value.values())
    if isinstance(value, list):
        return all(finite_tree(v) for v in value)
    return True

def digest(value):
    if not finite_tree(value):
        raise ValueError('nonfinite_tree')
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def sha_ok(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None

def singleton_eligibility(resident_count, age_interval_years=None):
    """Research frame boundary, not legal adulthood or source-pool QC."""
    if isinstance(resident_count, bool) or not isinstance(resident_count, int) or resident_count < 1:
        return 'unknown_invalid_resident_count'
    if resident_count != 1:
        return 'eligible_age_boundary_not_applicable'
    if not isinstance(age_interval_years, (list, tuple)) or len(age_interval_years) != 2:
        return 'unknown_singleton_age'
    lo, hi = age_interval_years
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in [lo, hi]) or not 0 <= lo <= hi:
        return 'unknown_singleton_age'
    if hi < 20:
        return 'excluded_under20_singleton'
    if lo >= 20:
        return 'eligible'
    return 'unknown_age_boundary'

def resolve_fact(field, candidate=None):
    """Admit a documented CURRENT-dwelling fact, never infer shape from H8.

    Only documented source schemas may call this with a candidate. Generic
    verified_current_dwelling evidence still needs actual external verification;
    this function checks completeness, not the truth of a document.
    """
    out = {'field': field, 'value': None, 'status': 'unknown', 'reasons': []}
    if not candidate or candidate.get('value') is None:
        out['reasons'] = ['no_direct_current_dwelling_evidence']
        return out
    c = deepcopy(candidate)
    e = c.get('evidence', {})
    required = ['source_id', 'source_sha256', 'field', 'question_or_document_locator',
                'reference_time', 'dwelling_binding_id', 'verification_id']
    if e.get('scope') != 'current_dwelling' or any(not e.get(k) for k in required) or not sha_ok(e.get('source_sha256')):
        out['reasons'] = ['current_dwelling_evidence_incomplete']
        return out
    source = e['source_id']
    if field in ['dwelling_form', 'household_internal_storeys']:
        if source.startswith('CHFS2021') or source.startswith('census2020'):
            out['reasons'] = ['reviewed_source_has_no_direct_household_shape_or_internal_storeys_field']
            return out
        if e.get('kind') != 'verified_current_dwelling' or not e.get('independent_verified', False):
            out['reasons'] = ['shape_or_internal_storeys_not_independently_verified']
            return out
        if field == 'household_internal_storeys' and (isinstance(c['value'], bool) or not isinstance(c['value'], int) or c['value'] < 1):
            out['reasons'] = ['internal_storeys_invalid']
            return out
    elif field == 'building_construction_year' and source.startswith('CHFS2021'):
        m = re.fullmatch(r'c2012a_([1-6])', e['field'])
        if not m or e.get('current_owned_dwelling_index') != int(m[1]) or e.get('current_owned_marker_count') != 1 or e.get('tenure') != 1 or e.get('disposed', False):
            out['reasons'] = ['construction_year_not_bound_to_unique_current_owned_dwelling']
            return out
        if isinstance(c['value'], bool) or not isinstance(c['value'], int) or not 1900 <= c['value'] <= 2029:
            out['reasons'] = ['CHFS_construction_year_outside_question_range']
            return out
    elif field == 'building_age_bin' and source.startswith('CHFS2021'):
        if e['field'] != 'c1000ak' or e.get('tenure') not in [2, 3]:
            out['reasons'] = ['age_bin_not_current_nonowned_branch']
            return out
    elif e.get('kind') != 'verified_current_dwelling' or not e.get('independent_verified', False):
        out['reasons'] = ['unsupported_field_or_unverified_bridge']
        return out
    if not finite_tree(c):
        out['reasons'] = ['nonfinite_candidate']
        return out
    out.update(value=c['value'], status='source_supported_current_dwelling', evidence=e)
    return out

def validate_experiment(record, lock):
    """Check conditions, strong provenance binding, preregistered support.

    actual_mismatch_axes must come from the independently executed prototype
    resolver. A caller assertion cannot replace that resolver or byte hashing.
    """
    errors = []
    def require(ok, code):
        if not ok:
            errors.append(code)
    if not isinstance(record,dict) or not isinstance(lock,dict):
        return {'passed': False, 'errors': ['experiment_or_lock_not_object']}
    if not finite_tree(record) or not finite_tree(lock):
        return {'passed': False, 'errors': ['nonfinite_experiment_or_lock']}
    for key in ['unknown_population_fields', 'actual_mismatch_axes']:
        if not isinstance(record.get(key),list) or any(not isinstance(x,str) or not x for x in record[key]):
            return {'passed': False, 'errors': ['invalid_axis_list_' + key]}
    auth0=record.get('conditional_evidence',{})
    if not isinstance(auth0,dict) or not isinstance(record.get('exposure'),dict) or not isinstance(record.get('prototype_target'),dict):
        return {'passed': False, 'errors': ['condition_or_target_not_object']}
    for key in ['accepted_unknown_population_fields','approved_mismatch_axes']:
        if not isinstance(auth0.get(key),list) or any(not isinstance(x,str) or not x for x in auth0[key]):
            return {'passed': False, 'errors': ['invalid_authorization_axis_list_' + key]}
    require(record.get('claim_track') == 'conditional_engineering', 'conditional_track_required')
    require(record.get('population_frequency_claim') is False, 'branch_frequency_is_not_population_frequency')
    require(record.get('empirical_transport_verified') is False, 'empirical_transport_not_established')
    require(record.get('housing_before_sha256') == record.get('housing_after_sha256') and sha_ok(record.get('housing_before_sha256')), 'population_housing_changed_or_unbound')
    require(record.get('family_before_sha256') == record.get('family_after_sha256') and sha_ok(record.get('family_before_sha256')), 'population_family_changed_or_unbound')
    require(sha_ok(record.get('profile_file_sha256')), 'profile_bytes_unbound')
    require(isinstance(record.get('prototype_group_id'),str) and bool(record.get('prototype_group_id')) and sha_ok(record.get('source_idf_sha256')) and sha_ok(record.get('parent_idf_sha256')) and sha_ok(record.get('weather_sha256')), 'actual_source_or_weather_bytes_unbound')
    e = record.get('exposure', {})
    auth = record.get('conditional_evidence', {})
    require(auth.get('kind') == 'predeclared_conditional_design', 'explicit_design_authorization_required')
    require(bool(auth.get('evidence_id')) and bool(auth.get('rationale')), 'authorization_locator_or_rationale_missing')
    require(auth.get('source_group_id') == record.get('prototype_group_id'), 'authorization_source_group_mismatch')
    require(auth.get('target_sha256') == digest(record.get('prototype_target', {})), 'authorization_target_mismatch')
    require(auth.get('exposure_sha256') == digest(e), 'authorization_exposure_mismatch')
    unknown = record.get('unknown_population_fields', [])
    accepted = auth.get('accepted_unknown_population_fields', [])
    require(len(set(unknown)) == len(unknown) and len(set(accepted)) == len(accepted) and set(unknown) == set(accepted), 'unknown_dimensions_not_exactly_accepted')
    mismatch = record.get('actual_mismatch_axes', [])
    approved = auth.get('approved_mismatch_axes', [])
    require(len(set(mismatch)) == len(mismatch) and len(set(approved)) == len(approved) and set(mismatch) == set(approved), 'transport_axes_not_exactly_approved')
    require(auth.get('population_type_identified') is False, 'design_promoted_to_population_shape')
    require(lock.get('frozen_before_first_run') is True, 'sensitivity_plan_not_preregistered')
    require(record.get('experiment_lock_sha256') == digest(lock), 'experiment_lock_mismatch')
    # This chronology is only local recorded evidence, not a trusted timestamp.
    try:
        require(datetime.fromisoformat(lock['locked_at']) < datetime.fromisoformat(record['first_run_at']), 'lock_not_before_first_run')
    except (KeyError, TypeError, ValueError):
        require(False, 'chronology_missing_or_invalid')
    require(sha_ok(lock.get('source_registry_sha256')) and sha_ok(lock.get('weather_registry_sha256')) and isinstance(lock.get('code_sha256'),dict) and bool(lock.get('code_sha256')) and all(sha_ok(x) for x in lock['code_sha256'].values()), 'lock_dependencies_missing')
    require(record.get('profile_file_sha256') == lock.get('profile_file_sha256'), 'lock_profile_mismatch')
    pair = {'source_group_id': record.get('prototype_group_id'),
            'prototype_target_sha256': digest(record.get('prototype_target', {})),
            'weather_sha256': record.get('weather_sha256'),
            'source_idf_sha256':record.get('source_idf_sha256'),
            'parent_idf_sha256':record.get('parent_idf_sha256')}
    require(pair in lock.get('admitted_transport_pairs', []), 'transport_pair_not_predeclared')
    grids = lock.get('sensitivity_grids', {})
    for field in ['north_axis_deg', 'infiltration_ach', 'gross_to_zone_floor_ratio', 'floor_position', 'geometry_family', 'ground_temperature_c']:
        require(field in e and e.get(field) in grids.get(field, []), 'condition_not_locked_' + field)
    primary = lock.get('main_conditions', {})
    require(all(v in grids.get(k, []) for k, v in primary.items()) and bool(primary), 'main_conditions_outside_locked_support')
    require(lock.get('pairing_unit') == 'family_slot_id' and lock.get('variant_is_new_population_sample') is False, 'paired_variants_miscounted_as_population_samples')
    require(record.get('family_slot_id') in lock.get('family_slots', []), 'slot_not_in_preserved_denominator')
    require(lock.get('keep_refusals_in_denominator') is True and lock.get('select_by_output') is False, 'outcome_selection_or_refusal_drop')
    ratio=e.get('gross_to_zone_floor_ratio');ach=e.get('infiltration_ach');angle=e.get('north_axis_deg')
    require(isinstance(ratio, (int,float)) and not isinstance(ratio,bool) and 0 < ratio <= 1, 'geometry_ratio_invalid')
    require(isinstance(ach, (int,float)) and not isinstance(ach,bool) and 0 <= ach <= 10, 'engineering_ach_support_invalid')
    require(isinstance(angle,(int,float)) and not isinstance(angle,bool) and 0 <= angle < 360, 'orientation_invalid')
    return {'passed': not errors, 'errors': errors, 'scope': VERSION,
            'calibration_certified': False, 'population_representation_certified': False}
