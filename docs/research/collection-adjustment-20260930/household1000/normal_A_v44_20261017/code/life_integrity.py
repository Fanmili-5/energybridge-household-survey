"""Independent saved-calendar readback, including prior travel and real meal location."""
def inspect_day(day):
    errors=[]
    for mid,seq in day['member_calendars'].items():
        cells={t:(x['activity'],x['location'])for x in seq for t in range(x['start_min'],x['end_min'],10)}
        for trip in day['protected_travel_ledger'][mid]:
            if any(cells[t]!=(trip['activity'],'outside')for t in range(trip['start_min'],trip['end_min'],10)):
                errors.append([mid,'PREDECLARED_TRAVEL_OVERWRITTEN'])
        meal=day['meal_appointments'][mid];start=meal['actual_lunch_min']
        if any(cells[t]!=('meal_and_rest',meal['location'])for t in range(start,start+30,10)):
            errors.append([mid,'LUNCH_NOT_ONE_CONTIGUOUS_APPOINTMENT'])
    return errors
