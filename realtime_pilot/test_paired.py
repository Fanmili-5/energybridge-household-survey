"""Paired contracts: chronology, independence, missingness, saved targets and process cleanup."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from common import normalize_answers,digest
from paired_contract import LOOKUP,QUESTIONS,CONTEXT,prepare,validate,profile_components,display_pair
from proposal_contract import executable
from eb_execution import replay, upstream, ordinary
from verify_paired_physics import answers
from household_classification import feature_record,distance,pam,ari,fit
from test_pilot import NoExecute
from server import Store

class PairedTests(unittest.TestCase):
    def profile(self):return normalize_answers(answers(),list(LOOKUP),LOOKUP)
    def test_random_event_is_reproducible_and_independent_of_attitudes(self):
        p=self.profile();o,s=prepare(p,'seed');q=copy.deepcopy(p);q['P_COMFORT']['value']='1'
        o2,s2=prepare(q,'seed');self.assertEqual(o,o2);self.assertEqual(s,s2)
        scenarios=[prepare(p,str(i))[1] for i in range(60)]
        times={s['event']['trigger_h'] for s in scenarios};self.assertEqual(times,{17,18,19})
        durations={s['event']['end_h']-s['event']['trigger_h'] for s in scenarios};self.assertEqual(durations,{1,2})
        self.assertTrue(all(s['sampling']['method']=='uniform_event_start_17_18_19_duration_1_2_v1' for s in scenarios))
        self.assertEqual(profile_components(p)['classification'],profile_components(q)['classification'])
    def test_upstream_runtime_rejects_started_tasks_and_accepts_advancing(self):
        from legacy_test_support import prepare
        o,s=prepare(self.profile(),'seed');s['decision_h']=19;p=executable(o)
        p['appliances']['washer_start_h']=20
        app=replay(o,validate(o,p,s),s)['applications'][-1]
        self.assertTrue(any(r['reason']=='service_already_started_or_completed' for r in app['rejections']))
        self.assertNotIn('washer_start_h',app['applied_actions'])
        s['decision_h']=17;p=executable(o);p['appliances']['washer_start_h']=17.5
        app=replay(o,validate(o,p,s),s)['applications'][-1]
        self.assertEqual(app['applied_actions']['washer_start_h'],17.5)
        # EB accepts a fractional start; the pilot must not add a 10-minute gate.
        p['appliances']['washer_start_h']=18.01
        app=replay(o,validate(o,p,s),s)['applications'][-1]
        self.assertEqual(app['applied_actions']['washer_start_h'],18.01)
        p['appliances']['washer_start_h']=16
        app=replay(o,p,s)['applications'][-1]
        self.assertTrue(any(r['reason']=='runtime_past' for r in app['rejections']))
    def test_ordinary_and_device_fields_are_source_native(self):
        o,s=prepare(self.profile(),'seed');runner,_=upstream()
        native=runner._manual_no_vpp_user_plan(persona_config=None,appliance_config=o['eb_appliance_config'],current_setpoint=25)
        self.assertEqual(executable(o),{'setpoint':native['setpoint'],'appliances':native['appliance_actions']})
        self.assertNotIn('H_dryer_dependency',LOOKUP)
        self.assertEqual(o['devices']['washer']['duration_h'],2)
        self.assertEqual(o['devices']['washer']['earliest_h'],8)
        self.assertIn('ev_charge_start_h',executable(o)['appliances'])
        self.assertIn('water_heater_preheat',executable(o)['appliances'])
        self.assertNotIn('scoring_weights',json.dumps(o))
        p=executable(o);p['appliances']['water_heater_preheat']=False
        e=replay(o,p,s);app=next(a for a in e['applications'] if a['kind']=='proposal')
        self.assertIs(app['applied_actions']['water_heater_preheat'],False)
        self.assertEqual(e['rows'][-1]['actuators']['water_heater'],40)
    def test_required_habits_not_imputed_and_no_devices_skip_generation(self):
        p=self.profile();p['H_washer']={'value':None,'response_status':'skipped'}
        with self.assertRaises(ValueError):prepare(p,'seed')
        p['B05']['value']=['none']
        with self.assertRaisesRegex(ValueError,'资料已保存.*不生成两份方案'):
            prepare(p,'seed')
    def test_fact_distance_not_label_leakage(self):
        p=self.profile();a=feature_record(p)['features'];q=copy.deepcopy(p);q['score']={'value':5,'response_status':'answered'};q['P_COST']['value']='1'
        b=feature_record(q)['features'];self.assertEqual(a,b);self.assertEqual(distance(a,b),0)
        q['B02']['value']='6_plus';b=feature_record(q)['features'];self.assertGreater(distance(a,b),0);self.assertEqual(distance(a,b),distance(b,a))
        q['B05']['value']=['home_ev'];c=feature_record(q)['features'];self.assertGreaterEqual(distance(a,c),0)
        self.assertEqual(fit([])['status'],'insufficient_households')
    def test_pam_partitions_known_separated_groups(self):
        values=np.array([0,.01,.02,.03,.04,1,1.01,1.02,1.03,1.04]);D=np.abs(values[:,None]-values[None,:])
        medoids,labels=pam(D,2);self.assertEqual(ari(labels,[0]*5+[1]*5),1);self.assertEqual(len(set(medoids)),2)
    def test_paired_saved_target_and_no_synthetic_human_override(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);store.pool.shutdown();store.pool=NoExecute()
            payload={'request_id':'paired_test_nonce_001','answers':answers(),'scenario_id':CONTEXT['id'],'scenario_understood':True,'engineering_test':False}
            j=store.create('owner',payload,paired_flow=True);self.assertEqual(j['data_origin'],'synthetic_engineering_test')
            p=executable(j['original_plan']);display={'rows':[],'prediction':{'status':'unit_test_fixture'}}
            from paired_contract import VERSION
            j.update(status='complete',result={'schema_version':VERSION,'proposal_plan':p,'original_plan_hash':digest(j['original_plan']),
                'proposal_plan_hash':digest(p),'display':display,'display_hash':digest(display),'prediction':display['prediction'],'simulation_status':'unit_test_fixture'})
            feedback={'choice':'reject','score':3,'comfort_score':2,'energy_score':4,'vpp_score':2,'comment':'测试回答',
              **{k:j['result'][k] for k in ('display_hash','original_plan_hash','proposal_plan_hash')}}
            store.decide(j['id'],'owner',feedback)
            row=json.loads((Path(d)/j['id']/'sft_candidate.json').read_text());target=json.loads(row['messages'][-1]['content'])
            self.assertEqual(target['decision'],'reject');self.assertEqual(target['score'],3);self.assertEqual(target['energy_score'],4)
            self.assertEqual(row['flow'],'paired_ep_v1');self.assertIn('H_washer',row['messages'][1]['content']);self.assertNotIn('测试回答',row['messages'][1]['content'])
            self.assertFalse(row['training_release']);self.assertTrue(store.decide(j['id'],'owner',feedback)['duplicate'])

if __name__=='__main__':unittest.main()
