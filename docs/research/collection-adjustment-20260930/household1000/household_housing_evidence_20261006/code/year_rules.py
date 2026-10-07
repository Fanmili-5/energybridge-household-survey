"""CHFS current-dwelling year/age semantics. Unknowns remain unknown.

Questionnaire PDF63: nonowned age interval;69: old property year;78:
new property year, skip for acquisition7 with tenure not2/6. Calendar year can
mean a major rebuild or expected completion, not energy-code compliance.
"""
import math
from numbers import Real

def integer(v):
    return int(v) if isinstance(v,Real) and math.isfinite(float(v)) and float(v).is_integer() else None

AGE_INTERVALS={1:[0,3],2:[3,5],3:[5,10],4:[10,20],5:[20,None]}

def derive_year(row,selected,visit_year,reference_year=2020):
    out={'status':'current_dwelling_unresolved','exact_reported_year':None,'age_interval_years':None,
         'reported_effective_year_interval':None,'source_field':None,'source_year_semantics':None,
         'reference_year_compatible':None,'year_imputed':False,'energy_code_compliance_observed':False,
         'source_record_is_actual2020_household':False,'branch_skip_condition':None}
    if not selected['selected']:return out
    j=selected['current_dwelling_slot'];tenure=selected['tenure_code']
    if j=='nonowned':
        code=integer(row.get('c1000ak'));out['source_field']='c1000ak'
        out['source_year_semantics']='categorical_age_interval_at_actual_visit; endpoints_not_precisely_identified'
        if code not in AGE_INTERVALS:
            out['status']='nonowned_age_missing_or_invalid_code';return out
        lower,upper=AGE_INTERVALS[code];out['age_interval_years']=[lower,upper]
        # Do not silently choose an exact calendar year from a reported range.
        out['reported_effective_year_interval']=[None if upper is None else visit_year-upper,visit_year-lower]
        out['status']='nonowned_reported_age_interval'
        out['reference_year_compatible']='overlap_requires_explicit_time_transport'
        return out
    if tenure!=1 or not isinstance(j,int):return out
    field=f'c2012a_{j}';year=integer(row.get(field));old=integer(row.get(f'c2000x_{j}')) in [1,2,3]
    acq=integer(row.get(f'c2006_{j}'));property_type=integer(row.get(f'c2008ab_{j}'))
    out['source_field']=field;out['source_year_semantics']='property_specific_completion_or_major_rebuild_year; projected_completion_possible'
    if not old:
        skip=True if acq==7 and property_type is not None and property_type not in [2,6] else False if acq is not None and (acq!=7 or property_type in [2,6]) else None
        out['branch_skip_condition']=skip
        if skip:
            out['status']='unasked_year_value_conflict' if year is not None else 'structurally_unasked_year';return out
        if skip is None:
            out['status']='year_eligibility_unresolved';return out
    else:out['branch_skip_condition']='old_branch_separate_year_question_PDF69'
    if year is None:out['status']='eligible_year_missing';return out
    if not 1900<=year<=2029:out['status']='outside_questionnaire_calendar_range';return out
    out['exact_reported_year']=year
    out['reference_year_compatible']=year<=reference_year
    if year>visit_year:out['status']='future_or_projected_year_not_completed_at_visit'
    elif year>reference_year:out['status']='post_reference_year_not_2020_stock_proxy'
    else:out['status']='reported_effective_year_reference_compatible'
    return out

def epoch(year):
    return 0 if year<1980 else 1 if year<2000 else 2 if year<2010 else 3
