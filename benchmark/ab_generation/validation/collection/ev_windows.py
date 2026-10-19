"""Read-only full-catalogue EV connection/observation boundary audit."""
import argparse
from pathlib import Path
from benchmark.ab_generation.common import read,save,verify


def audit(root):
    root=Path(root);verify(root);seen=set();extended=set();failures=[];tail_quarantine=0
    for path in sorted((root/'catalogues').glob('*.json.gz')):
        day=read(path);c=read(root/'contexts'/path.name)
        for raw in day['quarantined_requests']:
            tail_quarantine+=any('NOT_DEPARTURE_FAILURE' in r for r in raw['gate_issues'])
        for row in day['rows']:
            for child in row['components']:
                if child['family']!='ev' or child['id'] in seen:continue
                seen.add(child['id']);m=child['magnitude']
                controls=[r for r in c['A']['controls'] if r['kind']=='ev_charge_window' and r['asset_id']==child['asset_id'] and r['need_id']==child['service_need_id']]
                connection_end=max(r['end_min'] for r in controls);observation_end=min(connection_end,c['horizon_min'][1])
                if connection_end>observation_end:extended.add(c['case_id'])
                if (m['original_connection_end_min']!=connection_end or m['materialization_end_min']!=observation_end
                        or m['service_slack_min']-m['observation_slack_min']!=connection_end-observation_end):
                    failures.append(child['id'])
    return {'schema':'eb.collection.EV_boundary_review.v1','passed':not failures,
        'distinct_EV_requests':len(seen),'extended_connection_cases':sorted(extended),
        'tail_requests_quarantined_not_labeled_departure_failure':tail_quarantine,
        'failures':failures,'new_engine_runs':0,'A_connections_changed':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    result=audit(a.root);save(a.out,result);print(result)
    if not result['passed']:raise SystemExit(1)
