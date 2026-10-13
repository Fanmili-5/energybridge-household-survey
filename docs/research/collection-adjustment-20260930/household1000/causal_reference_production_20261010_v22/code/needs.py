"""Service uses and bounds precede A and do not consult operator free windows.

Neither cited activity models nor CHFS/CRECS identify personal deadlines.
These are explicit experimental service contracts; an actor may negotiate
changes. They are never labelled observed habits or inferred preferences.
"""
from common import rank
def batch_contract(w,date,kind,context,next_context):
    origin=1440
    if kind=='dishwasher':
        deadline=origin+next_context['family_context']['dinner_min']-30
        purpose='本批餐具在次日晚餐备餐前交付；早餐与午餐使用另组给定餐具'
        rule='given two-set meal inventory and next dated dinner; no operator window consulted'
    else:
        level=rank(w['household_id'],'v20-laundry-handover')%3
        minute=[720,1080,1200][level];deadline=origin+minute
        purpose='本批洁净衣物在次日'+f'{minute//60:02d}:00'+'前取出交付；无烘干时可穿时间未知'
        rule='predeclared clean-batch handover at next noon/evening; given purpose,not a measured wardrobe or hygiene limit'
    return {'delivery_deadline_min':deadline,'program_deadline_min':deadline-10,
        'service_purpose':purpose,'service_bound_evidence_kind':'given_experimental_service_contract',
        'service_bound_rule':rule,'deadline_uses_operator_availability':False,
        'subjective_importance':None,'willingness_to_change_bound':None,
        'actual_household_clothing_or_crockery_inventory_observed':False}
