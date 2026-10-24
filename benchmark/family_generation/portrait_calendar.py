"""Existing neighbor evidence for local timing only, never extra demand days."""
import copy
import datetime as dt

from .core import digest,require

FIELD='calendar_neighbor_evidence'


def add_calendar_evidence(context,available,receipts=None):
    """Append declared evidence needed by source service horizons; no retry."""
    from .device_persona import preference_input
    result=copy.deepcopy(context);source=preference_input(context)
    known={d['date']:d for d in source['days']};provided={}
    for day in available:
        date=day['date']
        require(date not in provided or provided[date]==day,'PORTRAIT_NEIGHBOR_DATE_CONFLICT')
        provided[date]=copy.deepcopy(day)
    # Use the existing whitelist/calendar validator, including busy intervals
    # and unchanged resident/external operator IDs, on the complete evidence.
    probe=copy.deepcopy(context);probe['habit_days']=list(provided.values())+[
        d for date,d in known.items() if date not in provided]
    normalized=preference_input(probe)
    evidence={d['date']:d for d in normalized['days']}
    require(all(evidence[date]==day for date,day in known.items()),'PORTRAIT_NEIGHBOR_DISAGREES_WITH_SELECTED_CALENDAR')
    needed=set()
    for need in source['declared_service_contracts']:
        origin=dt.date.fromisoformat(need['source_date'])
        for offset in range(max(0,need['release_min']//1440),need['deadline_min']//1440+1):
            needed.add(str(origin+dt.timedelta(days=offset)))
    extra=[evidence[date] for date in sorted(needed-set(known)) if date in evidence]
    record={'schema':'eb.portrait.calendar_evidence.v1','days':extra,
            'source_receipts':{date:sorted(copy.deepcopy((receipts or {}).get(date,[])),key=digest) for date in sorted({d['date'] for d in extra})},
            'unavailable_needed_dates':sorted(needed-set(evidence)),
            'scope':'existing_neighbor_availability_only;not_habit_days_new_services_or_new_operators'}
    record['evidence_sha256']=digest(record)
    previous=result.setdefault('energy_preferences',{}).get(FIELD)
    require(previous is None or previous==record,'PORTRAIT_NEIGHBOR_EVIDENCE_REPLACED')
    result['energy_preferences'][FIELD]=record
    return result


def availability_source(source):
    """Merge evidence into a local copy only; selected portrait days stay fixed."""
    record=source.get('energy_preferences',{}).get(FIELD)
    if record is None:return source
    require(record['evidence_sha256']==digest({k:v for k,v in record.items() if k!='evidence_sha256'}),'PORTRAIT_NEIGHBOR_EVIDENCE_HASH')
    from .device_persona import preference_input
    probe=copy.deepcopy(source);base={d['date']:d for d in source['days']}
    for day in record['days']:
        require(day['date'] not in base,'PORTRAIT_NEIGHBOR_REPLACES_SELECTED_DATE')
        base[day['date']]=day
    probe['habit_days']=list(base.values())
    checked=preference_input(probe)
    result=copy.deepcopy(source);result['days']=checked['days']
    return result
