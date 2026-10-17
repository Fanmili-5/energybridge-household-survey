"""Pre-A services under the user's daily configured-appliance requirement."""
from common import rank

def profile(w):
    r=w['routine']
    return {'warm_day_multiplier':1.20,'weekly_linen_kg_per_resident':.35,
            'linen_weekday':rank(w['household_id'],'linen-weekday')%7,
            'target_batch_kg':r['laundry_batch_kg'],
            'maximum_batch_kg':4.5,'maximum_dirty_wait_days':7,
            'source_weekly_frequency':w['source_V33_routine']['wash_count_reference_per_week'],
            'source_frequency_retained_as_lineage_not_daily_task_frequency':True,
            'daily_laundry_required_if_owned':True,
            'daily_laundry_reference_kg':r['laundry_batch_kg'],
            'profile_evidence_kind':'user-given daily appliance task coverage;size-conditioned reference batch mass;not source-observed daily usage',
            'automatic_delayed_start_given':True,'maximum_preload_wait_min':720,
            'daily_dishwasher_if_owned':True,'daily_bath_if_water_heater_owned':True,
            'daily_use_removed_for_diversity':False}

def textile_input(w,p,date,weather):
    ordinary=p['daily_laundry_reference_kg']
    warm=weather['maximum_C']>=28
    linen=p['weekly_linen_kg_per_resident']*w['N'] if date.weekday()==p['linen_weekday'] else 0.
    return round(ordinary*(p['warm_day_multiplier']if warm else 1.)+linen,6), {
        'prior_day_garments_available_at_midnight':True,'warm_day_change':warm,
        'scheduled_household_linen_kg':linen,'uses_B_or_price_or_event':False}

def wants_laundry(p,date,inventory,oldest):
    return inventory>1e-8
