import copy
import itertools
import unittest
from pathlib import Path

from ..common import read,digest
from ..model import apply
from .a_solver import compile_life,solve
from .automatic_programs import bind_reference_contract
from .contract import config
from .dated_target_context import derive
from .independent import audit
from .pipeline import fresh_context
from .candidates import prepare,program_grammar,legacy_config
from benchmark.research_delivery.a_review import inspect

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    spec=copy.deepcopy(read(ROOT/'examples/life/life_batch.json')['households'][0])
    world=copy.deepcopy(read(ROOT/'examples/life/resource_worlds.json')['households'][0])
    spec['end_exclusive']='2025-07-03'
    washer=next(d for d in world['devices'] if d['kind']=='washer')
    dryer=next(d for d in world['devices'] if d['kind']=='dryer')
    washer.update(types=['washer','dryer'],automatic_programs=['washer','dryer'])
    washer['parameters']={'washer':copy.deepcopy(washer['parameters']),
                          'dryer':copy.deepcopy(dryer['parameters']),'nameplate_W':2500}
    world['devices']=[d for d in world['devices'] if d is not dryer]
    for m in world['members']:
        m['can_operate_asset_ids']=[a for a in m['can_operate_asset_ids'] if a!=dryer['asset_id']]
    child=next(p for p in spec['program_policies'] if p['kind']=='dryer')
    child['asset_id']=washer['asset_id']
    return spec,world


class AutomaticProgramsTests(unittest.TestCase):
    def setUp(self):
        self.spec,self.world=fixture()

    def test_fresh_A_has_one_asset_one_handling_chain_and_all_phases(self):
        before=digest([self.spec,self.world]);p=compile_life(self.spec,self.world)
        a=solve(p,deterministic_time=2)
        self.assertEqual('feasible',a['status']);self.assertTrue(inspect(p,a['A'],a['ev_charging_steps'])['passed'])
        self.assertEqual(before,digest([self.spec,self.world]));self.assertIsNone(p['legacy_comparator'])
        for j in p['jobs']:
            if not j.get('automatic_child_need_id'):continue
            parent=next(t for t in a['A']['tasks'] if t['need_id']==j['need_id'])
            child=next(t for t in a['A']['tasks'] if t['need_id']==j['automatic_child_need_id'])
            self.assertEqual(parent['asset_id'],child['asset_id']);self.assertEqual(parent['end_min'],child['start_min'])
            ops=[o for o in a['A']['operations'] if o['need_id'] in (parent['need_id'],child['need_id'])]
            self.assertEqual(['load','unload'],sorted(o['kind'] for o in ops))
            self.assertTrue(all(o['need_id']==parent['need_id'] for o in ops))
            self.assertGreaterEqual(next(o for o in ops if o['kind']=='unload')['start_min'],child['end_min'])

    def test_dual_type_does_not_invent_automatic_capability(self):
        washer=next(d for d in self.world['devices'] if d['kind']=='washer');washer.pop('automatic_programs',None)
        with self.assertRaisesRegex(ValueError,'CAPABILITY_NOT_EXPLICIT'):compile_life(self.spec,self.world)

    def test_missing_phase_power_is_not_copied_from_washer(self):
        washer=next(d for d in self.world['devices'] if d['kind']=='washer');washer['parameters'].pop('dryer')
        with self.assertRaisesRegex(ValueError,'PARAMETERS_NOT_EXPLICIT'):compile_life(self.spec,self.world)

    def test_source_contract_binding_is_explicit_reversible_and_idempotent(self):
        washer=next(d for d in self.world['devices'] if d['kind']=='washer');washer.pop('automatic_programs')
        original=copy.deepcopy(self.world)
        bound,ledger=bind_reference_contract(self.world,'reference50_A46_combo_v1')
        self.assertEqual(original,self.world);self.assertEqual(1,len(ledger['bindings']))
        restored=copy.deepcopy(bound)
        for d in restored['devices']:
            if d['asset_id']=='washer':d.pop('automatic_programs');d.pop('automatic_programs_source')
        self.assertEqual(original,restored)
        self.assertEqual(bound,bind_reference_contract(bound,'reference50_A46_combo_v1')[0])
        self.assertFalse(ledger['uses_A_or_daily_requirements']);self.assertEqual(0,ledger['new_random_draws'])

    def test_source_binding_uses_existing_compile_entry_and_same_phase_plan(self):
        explicit=solve(compile_life(self.spec,self.world),deterministic_time=2)
        next(d for d in self.world['devices'] if d['kind']=='washer').pop('automatic_programs')
        self.spec.setdefault('provenance',{})['program_capability_contract']='reference50_A46_combo_v1'
        problem=compile_life(self.spec,self.world);bound=solve(problem,deterministic_time=2)
        self.assertEqual(explicit['A'],bound['A'])
        self.assertTrue(inspect(problem,bound['A'],bound['ev_charging_steps'])['passed'])
        self.assertEqual(digest(self.world),problem['source_world_sha256'])
        self.assertEqual(1,len(problem['automatic_capability_binding']['bindings']))

    def test_source_binding_does_not_accept_unknown_contract_or_plan_inputs(self):
        with self.assertRaisesRegex(ValueError,'UNKNOWN_AUTOMATIC_REFERENCE_CONTRACT'):
            bind_reference_contract(self.world,'unverified_combo')
        with self.assertRaisesRegex(ValueError,'PLAN_INFORMATION'):
            bind_reference_contract({**self.world,'A':{}},'reference50_A46_combo_v1')
        with self.assertRaisesRegex(ValueError,'DOWNSTREAM'):
            bind_reference_contract({**self.world,'human_score':0},'reference50_A46_combo_v1')

    def test_phase_power_uses_separate_supply_intervals(self):
        p=compile_life(self.spec,self.world);p['jobs']=[j for j in p['jobs'] if j['asset_id']=='washer']
        p['world']['devices']=[d for d in p['world']['devices'] if d['kind']!='ev']
        p['fixed_operations']=[];p['EV']={'journeys':[],'connections':[],'failures':[]}
        p['world']['electrical']={'supply_W':1000}
        washer=next(d for d in p['world']['devices'] if d['kind']=='washer')
        washer['parameters']['dryer'].update(power_kw=2.5,nameplate_W=2500)
        for j in p['jobs']:j['policy']['energy_model']='legacy_constant_power'
        self.assertEqual('infeasible',solve(p,deterministic_time=2)['status'])
        washer['parameters']['dryer']['power_kw']=.5
        a=solve(p,deterministic_time=2);self.assertEqual('feasible',a['status'])
        self.assertTrue(inspect(p,a['A'],a['ev_charging_steps'])['passed'])

    def test_same_asset_multiple_batches_do_not_overlap_holds(self):
        root=next(p for p in self.spec['program_policies'] if p['kind']=='washer')
        root.update(initial_inventory_kg=6,daily_quantity_kg=1,daily_service=True)
        # This test isolates shared hold intervals, with explicitly fixed power.
        for policy in self.spec['program_policies']:policy['energy_model']='legacy_constant_power'
        p=compile_life(self.spec,self.world);a=solve(p,deterministic_time=2)
        self.assertEqual('feasible',a['status']);self.assertTrue(inspect(p,a['A'],a['ev_charging_steps'])['passed'])
        roots=[j for j in p['jobs'] if j.get('automatic_child_need_id') and j['date']==p['anchor']]
        self.assertEqual(2,len(roots));intervals=[]
        for j in roots:
            ops=[o for o in a['A']['operations'] if o['need_id']==j['need_id']]
            intervals.append((min(o['start_min'] for o in ops),max(o['end_min'] for o in ops)))
        intervals.sort();self.assertLessEqual(intervals[0][1],intervals[1][0])

    def test_automatic_cycle_crosses_midnight_without_transfer(self):
        p=compile_life(self.spec,self.world)
        p['jobs']=[j for j in p['jobs'] if j['asset_id']=='washer' and j['date']==p['anchor']]
        p['world']['devices']=[d for d in p['world']['devices'] if d['kind']!='ev']
        p['fixed_operations']=[];p['EV']={'journeys':[],'connections':[],'failures':[]}
        for j in p['jobs']:
            j.update(release_min=1380,deadline_min=1900,preferred_start_min=1420)
            j['policy']['machine_windows_min']=[[0,1440]]
        for day in p['days'].values():day.update(operator_windows={'adult1':[]},reservations=[])
        p['days'][p['anchor']]['operator_windows']={'adult1':[[1380,1440],[1530,1900]]}
        a=solve(p,deterministic_time=2);self.assertEqual('feasible',a['status'])
        self.assertTrue(inspect(p,a['A'],a['ev_charging_steps'])['passed'])
        wash=next(t for t in a['A']['tasks'] if t['kind']=='washer');dry=next(t for t in a['A']['tasks'] if t['kind']=='dryer')
        self.assertLess(wash['start_min'],1440);self.assertGreater(dry['end_min'],1440)
        self.assertEqual(wash['end_min'],dry['start_min'])

    def test_conditional_target_uses_one_draw_and_fixed_dry_offset(self):
        p=compile_life(self.spec,self.world)
        profile={'household_id':p['household_id'],'joint_sampling':{'devices':[dict(
            asset_id='washer',kind='washer',coordinates={'time_orientation':.7})]}}
        result=derive(p,profile);rows={r['need_id']:r for r in result['rows']}
        self.assertEqual(0,result['new_random_draws'])
        for j in p['jobs']:
            if not j.get('automatic_parent_need_id'):continue
            parent=rows[j['automatic_parent_need_id']];child=rows[j['need_id']]
            duration=next(x['policy']['duration_min'] for x in p['jobs'] if x['need_id']==j['automatic_parent_need_id'])
            self.assertEqual(parent['target_min']+duration,child['target_min'])
            self.assertFalse(child['independent_source_target_applied'])
        a=solve(p,profile,deterministic_time=2,target_mode='life_conditional_v1')
        self.assertEqual('feasible',a['status']);self.assertTrue(inspect(p,a['A'],a['ev_charging_steps'])['passed'])

    def test_independent_auditors_reject_transfer_or_phase_gap(self):
        p=compile_life(self.spec,self.world);a=solve(p,deterministic_time=2)
        context=fresh_context(p,a,p['anchor'],{},config())
        bad=copy.deepcopy(a['A']);child=next(t for t in bad['tasks'] if t['kind']=='dryer')
        child['start_min']+=10;child['end_min']+=10
        self.assertFalse(inspect(p,bad,a['ev_charging_steps'])['passed'])
        relative=copy.deepcopy(context['A']);t=next(t for t in relative['tasks'] if t['kind']=='dryer')
        t['start_min']+=10;t['end_min']+=10
        self.assertIn('AUTOMATIC_PHASE_NOT_IMMEDIATE',audit(context,context['A'],relative))
        bad=copy.deepcopy(a['A']);root=next(o for o in bad['operations'] if o['kind']=='load' and o['asset_id']=='washer')
        bad['operations'].append({**root,'operation_id':'invented','need_id':root['need_id']+':dry'})
        self.assertFalse(inspect(p,bad,a['ev_charging_steps'])['passed'])

    def test_original_B_adapter_preserves_the_shared_chain(self):
        p=compile_life(self.spec,self.world);a=solve(p,deterministic_time=2)
        cfg=config();c=fresh_context(p,a,p['anchor'],{},cfg);self.assertFalse(audit(c,c['A'],c['A']))
        view=prepare(c,cfg);device=next(d for d in view['devices'] if d['asset_id']=='washer')
        raws=list(itertools.islice(program_grammar(view,device,legacy_config(cfg)),20))
        self.assertTrue(raws)
        for raw in raws:
            tasks=[t for patch in raw['patches'] if patch.get('collection')=='tasks' for t in patch['rows']]
            self.assertEqual({'washer','dryer'},{t['kind'] for t in tasks})
            wash=next(t for t in tasks if t['kind']=='washer');dry=next(t for t in tasks if t['kind']=='dryer')
            self.assertEqual(wash['end_min'],dry['start_min'])
            self.assertEqual(wash['asset_id'],dry['asset_id'])

    def test_original_service_declaration_without_new_device_marker_is_checked(self):
        p=compile_life(self.spec,self.world);a=solve(p,deterministic_time=2)
        c=fresh_context(p,a,p['anchor'],{},config())
        for d in c['devices']:d.pop('automatic_programs',None)
        for n in c['needs']:n.pop('automatic_child_need_id',None)
        bad=copy.deepcopy(c['A']);child=next(t for t in bad['tasks'] if t['kind']=='dryer')
        root=child['need_id'][:-4]
        child['start_min']+=10;child['end_min']+=10
        unload=next(o for o in bad['operations'] if o['kind']=='unload' and o['need_id']==root)
        unload['start_min']+=10;unload['end_min']+=10
        self.assertIn('AUTOMATIC_PHASE_NOT_IMMEDIATE',audit(c,c['A'],bad))

    def test_automatic_capability_does_not_invent_drying_requirement(self):
        p=compile_life(self.spec,self.world);a=solve(p,deterministic_time=2)
        c=fresh_context(p,a,p['anchor'],{},config())
        c['A']['tasks']=[t for t in c['A']['tasks'] if t['kind']!='dryer']
        c['needs']=[n for n in c['needs'] if n['kind']!='dryer']
        for n in c['needs']:
            n.pop('automatic_child_need_id',None)
            if n['kind']=='washer':n['wash_only_delivery']='clean wet textiles to basket;passive drying not simulated'
        self.assertFalse(audit(c,c['A'],c['A']))


if __name__=='__main__':unittest.main()
