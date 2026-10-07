#!/usr/bin/env python3
"""Evidence-bounded CHFS residence/generation/current-dwelling bridge.

Pure functions consume source-native fields (missing normalized to None).
They do not fabricate census observation, whole-dwelling exclusive occupation,
sleeping layouts or original record identities. Unknowns are explicit outputs.
"""
import math
from numbers import Real

# Relative to respondent, not necessarily household head. Positive = elder.
LEVEL={1:0,2:0,3:1,4:1,5:2,6:-1,7:-1,8:-2,9:-2,10:0}

def number(v):
    return float(v) if isinstance(v,Real) and math.isfinite(float(v)) else None

def integer(v):
    v=number(v)
    return int(v) if v is not None and v.is_integer() else None

def valid_area(v,upper):
    v=number(v)
    return v if v is not None and 1<=v<=upper else None

def multi_codes(v):
    """CHFS multi-selection strings are hyphen-separated; empty is unknown."""
    if isinstance(v,str):
        try:return set(map(int,v.strip().split('-'))) if v.strip() else None
        except ValueError:return None
    n=integer(v)
    return {n} if n is not None else None

def derive_members(members,visit_year,reported_economic_count=None):
    co=[m for m in members if integer(m.get('a2000c')) in [1,2]]
    known_res=all(integer(m.get('a2000c')) in [1,2,3,4] for m in members)
    n=len(co)
    birth_known=all(integer(m.get('a2005')) is not None and 1900<=integer(m['a2005'])<=visit_year for m in co)
    levels=[LEVEL.get(integer(m.get('a2001'))) for m in co]
    distinct=set(v for v in levels if v is not None)
    unknown=sum(v is None for v in levels)
    g=1 if n==1 else (len(distinct) if n>0 and not unknown else None)
    lower=max(1,len(distinct)) if n else None
    upper=min(n,len(distinct)+unknown) if n else None
    reported=integer(reported_economic_count)
    roster_match=reported is None or reported==len(members)
    respondent_count=sum(integer(m.get('a2001'))==1 for m in members)
    active_conflict=any((integer(m.get('a1108'))==2 or integer(m.get('a1106'))==4) and integer(m.get('a2000c')) in [1,2] for m in members)
    singleton_age_interval=None
    agegate='not_singleton'
    if n==1:
        if not birth_known:agegate='unknown_birth_year'
        else:
            delta=visit_year-integer(co[0]['a2005'])
            # Adult birthday is not supplied; year difference d means d-1..d.
            singleton_age_interval=[max(0,delta-1),delta]
            agegate='known_under20' if delta<20 else ('boundary19_to20_unknown' if delta==20 else 'known_at_least20')
    eligible=bool(n and known_res and roster_match and respondent_count==1 and not active_conflict and birth_known and
                  agegate not in ['known_under20','boundary19_to20_unknown','unknown_birth_year'])
    return {'economic_member_count':len(members),'reported_economic_count':reported,
        'reported_roster_consistent_or_unasked':roster_match,'respondent_count':respondent_count,
        'co_resident_count':n,'economic_nonresident_count':sum(integer(m.get('a2000c')) in [3,4] for m in members),
        'unknown_residence_count':sum(integer(m.get('a2000c')) not in [1,2,3,4] for m in members),
        'residence_complete':known_res,'all_coresident_birth_valid':birth_known,'active_member_conflict':active_conflict,
        'census_resident_count_observed':None,'residence_bridge_status':'matched_chfs_coresidence_proxy',
        'generation_count_proxy':g,'generation_min':lower,'generation_max':upper,
        'known_levels':sorted(distinct),'unknown_relationship_count':unknown,
        'generation_has_unoccupied_intermediate_level':bool(distinct and max(distinct)-min(distinct)+1>len(distinct)),
        'generation_status':'derived_occupied_generation_count' if g is not None else 'unresolved_relationships_or_no_coresidents',
        'generation_is_complete_family_graph':False,'single_age_gate':agegate,'singleton_age_interval_years':singleton_age_interval,
        'eligible_for_matching':eligible,'eligible_for_generation_matching':eligible and g is not None}

def sharing_owned(hh,j):
    yes=integer(hh.get(f'c2008ba_1_mc_{j}'))==1 or integer(hh.get(f'c2008ba_2_mc_{j}'))==1
    no=integer(hh.get(f'c2008ba_7788_mc_{j}'))==1
    codes=multi_codes(hh.get(f'c2008ba_{j}'))
    yes=yes or bool(codes and codes&{1,2})
    no=no or codes=={7788}
    if yes and no:return 'contradictory_partial_and_none'
    if yes:return 'partial_occupancy_requires_allocation'
    if no:return 'whole_current_owned_dwelling'
    return 'sharing_unknown'

def select_housing(hh):
    tenure=integer(hh.get('c1001'))
    current=[j for j in range(1,7) if integer(hh.get(f'c2008b_{j}'))==1]
    out={'tenure_code':tenure,'current_owned_marker_count':len(current),'current_dwelling_slot':None,
         'dwelling_selection_status':'current_tenure_unknown','selected':False,
         'recorded_building_area_m2':None,'recorded_usable_area_m2':None,
         'area_candidate_m2':None,'area_candidate_census_integer_m2':None,'area_origin':'unknown',
         'area_scope_supported':False,'sharing_scope':'unknown','branch_overlap':False,
         'recorded_usable_origin':'unknown','consistent_with_source_auto0_7':False,
         'usable_larger_than_building':False,'area_invalid_fields':[],
         'whole_property_room_count':None,'whole_property_hall_count':None,
         'room_count_h7_proxy':None,'room_proxy_category':None,'room_bridge_status':'not_observed_for_current_dwelling',
         'census_H7_observed':None,'ordinary_dwelling_status':'not_measured_by_CHFS_H5_equivalent',
         'physical_layout_ready':False}
    if tenure in [2,3]:
        if current:
            out['dwelling_selection_status']='nonowned_tenure_with_current_owned_marker_conflict'
            return out
        out.update(selected=True,dwelling_selection_status='current_nonowned_branch',current_dwelling_slot='nonowned')
        out['sharing_scope']=('whole_rented_dwelling' if tenure==2 and integer(hh.get('c1002ab'))==1 else
                              'shared_area_allocation_unknown' if tenure==2 and integer(hh.get('c1002ab')) in [2,3,4] else 'occupancy_scope_unknown')
        usable=valid_area(hh.get('c1004'),999999.99)
        if number(hh.get('c1004')) is not None and usable is None:out['area_invalid_fields'].append('c1004')
        out.update(recorded_usable_area_m2=usable,recorded_usable_origin='nonowned_reported_occupied_usable_area')
        if usable is not None:out.update(area_candidate_m2=usable*1.33,area_origin='c1004_times1_33_census_allowed_proxy')
    elif tenure==1:
        if len(current)!=1:
            out['dwelling_selection_status']='missing_current_marker' if not current else 'multiple_current_marker_conflict'
            return out
        j=current[0];old=integer(hh.get(f'c2000x_{j}'))
        if old==4:
            out['dwelling_selection_status']='current_marker_on_disposed_dwelling_conflict'
            return out
        out.update(selected=True,dwelling_selection_status='unique_current_owned_dwelling',current_dwelling_slot=j,
                   sharing_scope=sharing_owned(hh,j))
        b=valid_area(hh.get(f'c2003_{j}'),999999.99)
        u_new=valid_area(hh.get(f'c2004_{j}'),999.99)
        u_old=valid_area(hh.get(f'c2000c_{j}'),999.99)
        rooms=integer(hh.get(f'c2005aa1_{j}'));halls=integer(hh.get(f'c2005aa2_{j}'))
        for stem,upper in [('c2003',999999.99),('c2004',999.99),('c2000c',999.99)]:
            key=f'{stem}_{j}'
            if number(hh.get(key)) is not None and valid_area(hh[key],upper) is None:out['area_invalid_fields'].append(key)
        out.update(recorded_building_area_m2=b,
                   whole_property_room_count=rooms if rooms is not None and 0<=rooms<=99 else None,
                   whole_property_hall_count=halls if halls is not None and 0<=halls<=99 else None)
        overlap=old in [1,2,3] and any(x is not None for x in [b,u_new,rooms,halls])
        out['branch_overlap']=overlap
        if overlap:
            out['area_origin']='old_new_branch_overlap_requires_provenance_check'
            out['room_bridge_status']='old_new_branch_overlap_requires_provenance_check'
        elif old in [1,2,3]:
            out.update(recorded_usable_area_m2=u_old,recorded_usable_origin='old_corrected_usable' if old==3 else 'old_value_branch_origin_unverified')
            if u_old is not None and old==3:
                out.update(area_candidate_m2=u_old*1.33,area_origin='c2000c_times1_33_census_allowed_proxy')
            elif u_old is not None:out['area_origin']='old_value_branch_origin_unverified'
        else:
            out.update(recorded_usable_area_m2=u_new,recorded_usable_origin='new_usable_may_include_source_auto_conversion')
            if b is not None:
                out.update(area_candidate_m2=b,area_origin='c2003_source_building_area')
                if u_new is not None:
                    out['consistent_with_source_auto0_7']=math.isclose(u_new,0.7*b,rel_tol=1e-6,abs_tol=1e-3)
                    out['usable_larger_than_building']=u_new>b
            elif u_new is not None:
                out.update(area_candidate_m2=u_new*1.33,area_origin='c2004_times1_33_mixed_origin_proxy')
            if rooms is not None and 0<=rooms<=99:
                if out['sharing_scope']=='whole_current_owned_dwelling' and rooms>0:
                    out.update(room_count_h7_proxy=rooms,room_proxy_category=str(rooms) if rooms<5 else '5+',
                               room_bridge_status='CHFS_shi_excluding_hall_proxy_natural_room_difference_unresolved')
                else:out['room_bridge_status']='zero_rooms_or_shared_exclusive_room_count_unknown'
    if out['area_candidate_m2'] is not None:
        out['area_candidate_census_integer_m2']=math.floor(out['area_candidate_m2']+0.5)
        out['area_scope_supported']=out['sharing_scope'] in ['whole_current_owned_dwelling','whole_rented_dwelling'] and not out['branch_overlap'] and not out['usable_larger_than_building']
    return out
