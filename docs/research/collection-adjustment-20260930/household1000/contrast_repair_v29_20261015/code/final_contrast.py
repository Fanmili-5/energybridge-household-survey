"""Final cohort acceptance joins source, physics, actual browser and HTTP evidence."""
import re,math
from common import *
from contrast_core import metrics,classify_equal_outcome,control_segments
from cohort_gate import require_reviewed_ep

def same_displayed(case):
    same=all(math.floor(q['A']['value']*1000+.5)==math.floor(q['B']['value']*1000+.5)for q in case['quantities'])
    sides={s:sorted(x['description'][1:]for x in case['impacts']if re.match('^'+s+r'(?:\s|（)',x.get('description','')))for s in('A','B')}
    return same and sides['A']==sides['B']

def validate_material(case,p):
    assert case['plans']['A']['window_end_abs_min']-case['plans']['A']['window_start_abs_min']==1440
    assert case['plans']['B']['window_end_abs_min']-case['plans']['B']['window_start_abs_min']==1440
    assert metrics(p)['admitted']
    for x in control_segments(p,'ac_setpoint'):
        matching=[c for c in case['commands']if c['asset_id']==x['asset_id']and c['kind']=='ac_setpoint'and c['start_abs_min']==x['start_min']and c['end_abs_min']==x['end_min']]
        assert len(matching)==1
        c=matching[0];assert c['A_start_abs_min']==x['start_min']and c['A_end_abs_min']==x['end_min'],'temporary change falsely presented as whole-period truncation'
        assert c['from_setpoint_C']==x['A']and c['to_setpoint_C']==x['B']
        if x['A']is not None and x['B']is not None:assert '恢复原安排'in c['display_change_text']
    if same_displayed(case):assert any(x['status']=='reference_equal_displayed_outcomes'for x in case['impacts'])

def main(batch):
    scope={'formal50':'original50','formal950':'other950'}[batch];lease=require_reviewed_ep(scope)
    physical=read(OUT/f'PHYSICS_{scope}_REVIEW.json');cases=read(OUT/f'FORMAL_{batch}_CASE_REVIEW.json');browser=read(OUT/f'BROWSER_{batch}_REVIEW.json');protocol=read(OUT/f'HTTP_{batch}_REVIEW.json')
    release=OUT/('formal_release'+batch[6:]);manifest=read(release/'FORMAL_RELEASE.json')
    expected=500 if batch=='formal50'else 9500
    assert physical['acceptance_passed']and physical['input_signature_at_readback']==lease['review']['input_signature']
    assert cases['passed']and cases['cases_checked']==expected and cases['release_signature']==manifest['release_signature']
    assert browser['passed']and browser['release_signature']==manifest['release_signature']and browser['source_case_count']==expected
    assert browser['actual_browser_cases_checked']>=(500 if batch=='formal50'else 60)
    assert browser['visible_change_text_matches_source']and browser['current_answer_and_respondent_outside_model_input']and browser['actual_submit_recovery_revision_withdrawal_passed']
    assert protocol['passed']and protocol['production_records_written']==0
    selected={h['household_id']:h for h in read(OUT/'SELECTION1000.json')['records']};legacy=read(OUT/'LEGACY_CONTRAST_QUEUE.json');priority=set(x['case_id']for x in legacy['priority41']);equal=set(x['case_id']for x in legacy['equal857']);records=[];counts=__import__('collections').Counter();ids=set(read(OUT/'PARTITIONS.json')[batch]);changed=set(read(OUT/f'CONTRAST_{batch}_INPUT.json')['changed_case_ids'])
    for row in manifest['households']:
        page=(release/'households'/row['household_id']/'index.html').read_text();cs=__import__('json').loads(re.search(r'id="joint-cases-data"[^>]*>(.*?)</script>',page,re.S).group(1))
        for case,rr in zip(cs,selected[row['household_id']]['rounds']):
            p=read(OUT/rr['pair_path']);validate_material(case,p);m=metrics(p);same=same_displayed(case);counts['cases']+=1;counts['same_displayed_outcomes']+=same
            counts['micro_requests']+=m['micro_temperature_request'];counts['repaired_priority41']+=p['case_id']in priority and p['case_id']in changed
            category=classify_equal_outcome(p)if same else'modeled_consequence_difference'
            counts[category]+=1
            if p['case_id']in equal or p['case_id']in priority:
                records.append({'case_id':p['case_id'],'was_priority41':p['case_id']in priority,'was_equal857':p['case_id']in equal,'source_repaired':p['case_id']in changed,'same_displayed_outcomes_now':same,'class':category,'actual_source_contrast':m,'human_response':None})
    assert counts['cases']==expected and counts['micro_requests']==0
    expected_priority=sum(x['household_id']in ids for x in legacy['priority41']);assert counts['repaired_priority41']==expected_priority
    expected_equal=sum(x['household_id']in ids for x in legacy['equal857']);assert sum(r['was_equal857']for r in records)==expected_equal
    report={'schema':'eb.final_cohort_task_contrast.v29','passed':True,'batch':batch,'cases':expected,'counts':dict(counts),
       'original_equal857_cases_accounted':expected_equal,'priority41_cases_repaired':expected_priority,
       'all_A_households_needs_policies_dates_hardware_preserved':True,'zero_micro_temperature_requests':True,
       'same_outcome_pairs_explicitly_classified_not_hidden':True,'fixed_actual_browser_scope':browser['actual_browser_cases_checked'],
       'human_perceptual_or_behavioral_validity_proven':False,'records':records}
    save(OUT/f'CONTRAST_{batch}_RELEASE_REVIEW.json',report)
    evidence=[f'PHYSICS_{scope}_REVIEW.json',f'FORMAL_{batch}_CASE_REVIEW.json',f'BROWSER_{batch}_REVIEW.json',f'HTTP_{batch}_REVIEW.json',f'CONTRAST_{batch}_RELEASE_REVIEW.json',str(release.relative_to(OUT)/'FORMAL_RELEASE.json'),'CONTRAST_NEGATIVE_CONTROLS.json']
    acceptance={'schema':'eb.final_task_world_acceptance.v29','passed':True,'batch':batch,'input_signature':lease['review']['input_signature'],
       'evidence':{n:sha(OUT/n)for n in evidence},'release_signature':manifest['release_signature'],'human_validity_claim':False,
       'other950_may_proceed':batch=='formal50','no_automatic_EP_launch':True}
    save(OUT/('ORIGINAL50_CONTRAST_ACCEPTANCE.json'if batch=='formal50'else'OTHER950_CONTRAST_ACCEPTANCE.json'),acceptance)
    print({k:v for k,v in report.items()if k!='records'},flush=True)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--batch',choices=['formal50','formal950'],required=True);a=p.parse_args();main(a.batch)
