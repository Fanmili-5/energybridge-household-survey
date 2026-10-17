"""Declared dated service contexts, independent of B and simulation outcomes.

These are benchmark design conditions, not estimated Chinese diary frequencies.
Keep the source laundry frequency and the EB program/hardware parameters. Small
households use a declared two-day dish batch; larger households a daily batch.
No extra chore or journey is created in response to a missing B candidate.
"""
import datetime as dt
from common import rank

VERSION = 'eb.dated_service_context.20261016.1'


def services(w, date, day):
    small = w['N'] <= 2
    phase = rank(w['household_id'], 'dish-batch-phase') % 2
    due = not small or (date - dt.date(2025, 1, 1)).days % 2 == phase
    working = day['day_type'] in ('weekday', 'makeup_workday')
    habit = w['routine']['stable_habit_variation_level']
    # EB supplies both 13:00 and 20:00 household/persona routines. Household
    # habit stays fixed; a nonworking day offers the corresponding daytime use.
    preferred = (780 if habit % 2 == 0 else 1200) if working else 780
    return {'schema': VERSION, 'date': date.isoformat(), 'day_type': day['day_type'],
            'dishwasher_batch_due': due, 'dish_batch_period_days': 2 if small else 1,
            'dish_inventory_condition': 'given two daily sets; small household batches two days; not measured inventory',
            'laundry_preferred_start_min': preferred,
            'laundry_frequency_unchanged': True,
            'basis': ['household size', 'fixed household habit', 'dated work/holiday calendar'],
            'evidence_kind': 'researcher_given_EB_adapted',
            'empirical_frequency_or_preference_claim': False,
            'B_or_physical_outcomes_consulted': False}


def signature(pair):
    """Compare substantive first-day services, without date/ID/time jitter."""
    ns = [n for n in pair['needs_A'] if 0 <= n['release_min'] < 1440]
    counts = {}
    for n in ns:
        k = n['kind']; counts[k] = counts.get(k, 0) + 1
    # Durations/quantity and home vs outside time expose real context variation.
    day = pair['dated_activity_days'][0]
    outside = sum(i['end_min']-i['start_min'] for seq in day['member_calendars'].values()
                  for i in seq if i['location'] == 'outside')
    trip = day.get('transport')
    return {'services': counts, 'outside_person_minutes': outside,
            'trip_traction_kWh': trip['traction_kWh'] if trip else 0,
            'cooling_person_room_minutes': sum(n['quantity'] for n in ns if n['kind'] == 'ac')}
