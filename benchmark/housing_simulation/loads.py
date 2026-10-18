"""Activity-resolved internal gains; published mechanics and declared occupant scales."""
from .policy import reference


def activity_class(activity):
    if activity.startswith('sleep') or 'nap' in activity:return 'sleep'
    if activity=='cooking':return 'cooking'
    if activity=='handling':return 'handling'
    if activity=='bath':return 'standing'
    return 'seated'


def metabolic_watts(activity, scale=1):
    """Scale is an explicit scenario input, never an inferred age correction."""
    return reference('people')['activity_W'][activity_class(activity)]*scale


def cooking_minutes(day):
    calendars={**day['calendars'],**day['shared']['member_calendars']}
    return {t for events in calendars.values()for event in events
            if event.get('location')=='home'and event.get('activity')=='cooking'
            for t in range(event['start_min'],event['end_min'],10)}
