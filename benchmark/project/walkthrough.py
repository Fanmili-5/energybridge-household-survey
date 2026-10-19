"""Read-only source-to-v69 conservation audit. Never generate, repair or run A/B."""
import argparse
import json
from pathlib import Path
from benchmark.ab_generation.common import bound, read, sha
from .pipeline import check
from .questionnaire import display_plans, verify_questionnaire


def audit(project, questionnaire):
    project, questionnaire = Path(project), Path(questionnaire)
    check(project); verify_questionnaire(questionnaire)
    view = read(project/'VIEW.json'); source = {h['id']: h for h in view['households']}
    index = read(questionnaire/'public/index.json'); ledger = read(questionnaire/'AUDIT.json')['records']
    expected = {p['id']: (h, p) for h in source.values() for p in h['previews']}
    seen = set(); joint = []
    for hid in index['households']:
        h = source[hid]; profile = read(questionnaire/'public/households'/(hid+'.json'))
        assert profile['members'] == [{**m, 'local_id':'m%02d' % (i+1), 'sex': next(
            (f['sex'] for f in h['facts']['members'] if f['member_id']==m['member_id']), 'unknown')}
            for i, m in enumerate(h['members'])]
        assert profile['housing'] == h['housing']
        assert profile['members_count'] == h['facts']['N']
        assert profile['relationships'] == h['facts']['relationships']
        # The exterior EV alias is a display projection, never a physical room.
        projected = []
        for d in profile['devices']:
            d = dict(d)
            if 'source_room_id' in d:
                assert d['kind']=='ev' and d['placement']=='exterior' and d['source_room_id'] is None
                assert d['room_id']=='external_dedicated_ev_bay'
                d['room_id']=d.pop('source_room_id');d.pop('room_projection')
            projected.append(d)
        assert projected == h['devices']
    for row in index['cases']:
        c = read(bound(questionnaire/'public', row['path'])); sid = c['bindings']['sample_id']
        h, preview = expected[sid]; pair_path = bound(project, preview['artifact']); pair = read(pair_path)
        context = read(project/'contexts'/(h['id']+'.json.gz'))
        assert sid not in seen; seen.add(sid)
        assert c['household_id']==h['id'] and c['plans']==display_plans(pair)
        for key in ('A_commands_sha256','B_commands_sha256','information_set'):
            assert c['bindings'][key]==pair[key]
        assert c['bindings']['source_pair_sha256']==sha(pair_path)
        assert c['bindings']['housing_layout_sha256']==sha(project/'connected/shells'/h['id']/'layout.json')
        assert c['bindings']['family_sha256']==context['source']['family_sha256']
        assert c['project_presentation']['event_meter_scope']==context['event_meter_scope']
        assert c['VPP_requests']==[dict(e,notification_min=context['decision_min']) for e in context['events']]
        record=next(r for r in ledger if r['sample_id']==sid)
        assert record['static_valid']==preview['static_valid'] and record['static_issues']==preview['static_issues']
        assert record['stratum']==preview['category']
        if record['stratum']=='joint':
            joint.append({'sample_id':sid,'household_id':h['id'],
                **{k:preview['features'][k] for k in ('composition','unit_count','handling','axis')}})
    assert seen==set(expected)
    observed_families={f for r in joint for f in r['composition'].split('+')}
    available_families={d['kind'] for h in source.values() for d in h['devices']
                        if d['kind'] in ('washer','dishwasher','ev','ac','water_heater')}
    return {'schema':'eb.project.source_to_v69_audit.v1', 'passed':True,
        'project_manifest_sha256':sha(project/'MANIFEST.json'),
        'questionnaire_manifest_sha256':sha(questionnaire/'MANIFEST.json'),
        'households':len(index['households']), 'cases':len(seen),
        'literal_source_plans_events_profiles_and_bindings_checked':True,
        'invalid_retained':sum(not r['static_valid'] for r in ledger),
        'A_equals_B_retained':sum(r['unchanged_control'] for r in ledger),
        'selected_joint_requests':joint,
        'selected_joint_scope':'independent request units;linked dryer is not a separate unit',
        'selected_joint_device_families_not_observed':sorted(available_families-observed_families),
        'selected_joint_unit_counts_observed':sorted({int(r['unit_count']) for r in joint}),
        'selected_joint_has_three_or_more_units':any(int(r['unit_count'])>=3 for r in joint),
        'selected_joint_coverage_scope':'observed preview only;not proof that missing mechanisms are infeasible',
        'generated_or_replaced_cases':0, 'new_engine_runs':0, 'human_answers':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--questionnaire',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(audit(args.project,args.questionnaire),ensure_ascii=False))
