"""Independent failure and native-action checks for external event allocation."""
import ast,copy,json,tempfile,unittest
from pathlib import Path
from collections import Counter,defaultdict
from unittest.mock import patch
from . import scene_coverage as scene
from .cohort_coverage import load,write_gzip
from .unified.contract import config,entry_config
from .unified.materials import project
from . import test_daily_problem as fixtures
NATIVE=fixtures.NATIVE
MANIFEST=fixtures.MANIFEST
from .v9_date_adapter import generate_day_baseline
from .unified.candidates import prepare,raw_grammar
from .eb_alignment import bind_household
from .model import apply
from .paper_v1_native_replay import replay
from .eb_agent_contract import plan_errors
from .common import digest

class SceneContractTests(unittest.TestCase):
    def test_default_still_requires_original_fixed_event(self):
        cfg=entry_config(Path(__file__).with_name('GENERATION_REPAIR_CONFIG.json'))
        before=copy.deepcopy(cfg);new=scene.event_configuration(cfg,960)
        self.assertEqual(before,cfg);self.assertEqual(960,new['event']['start_min'])
        invalid=copy.deepcopy(cfg);invalid['event']['start_min']=960;invalid['event']['end_min']=1020
        with self.assertRaisesRegex(ValueError,'FIXED_18_19'):config(invalid)
    def test_event_grid_is_explicit_and_bounded(self):
        cfg=entry_config(Path(__file__).with_name('GENERATION_REPAIR_CONFIG.json'))
        for start in [True,950,961,1210,float('nan'),1000.0]:
            with self.subTest(start=start),self.assertRaises(ValueError):scene.event_configuration(cfg,start)
        for start in scene.GRID:
            c=scene.event_configuration(cfg,start);self.assertEqual(60,c['event']['end_min']-c['event']['start_min'])
    def test_scene_mode_does_not_allow_new_direction_duration_or_actions(self):
        cfg=scene.event_configuration(entry_config(Path(__file__).with_name('GENERATION_REPAIR_CONFIG.json')),960)
        for key,value in [('end_min',1030),('direction','up')]:
            bad=copy.deepcopy(cfg);bad['event'][key]=value
            with self.assertRaises(ValueError):config(bad)
        bad=copy.deepcopy(cfg);bad['invented_appliance_action']='stop_cooling'
        with self.assertRaises(ValueError):config(bad)
    def test_pinned_paper_reads_event_clock_from_event_input(self):
        tree=ast.parse(Path(__file__).with_name('paper_v1_clock_source.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_event_start_hod','_event_end_hod')]
        ns={};exec(compile(ast.Module(body=nodes,type_ignores=[]),'pinned-paper-events','exec'),ns)
        self.assertEqual(16,ns['_event_start_hod']({'trigger_h':16}))
        self.assertEqual(17,ns['_event_end_hod']({'end_h':17}))
        self.assertEqual(18,ns['_event_start_hod'](None))
    def test_questionnaire_fails_on_mismatched_scene(self):
        with self.assertRaisesRegex(ValueError,'SCENE_EVENT_MISMATCH'):
            project({'events':[{'start_min':1080,'end_min':1140}]},None,
                    {'scene_event':{'start_min':960,'end_min':1020}}, {})
    def test_questionnaire_fails_without_any_event(self):
        with self.assertRaisesRegex(ValueError,'EVENT_CONTEXT_REQUIRED'):project({},None,{'scene_policy':'evening_scene_grid_v1'}, {})
    def test_actual_native_scene_retains_A_and_original_action_contract(self):
        if not NATIVE.exists():self.skipTest('EB_NATIVE_SOURCE is required')
        case,reference,cfg=fixtures.NativeDailyTests().fixture(ev=True)
        e=generate_day_baseline(case,'2007-07-18',reference,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        self.assertEqual('accepted_plan_only',e['status'])
        A=copy.deepcopy(e['context']['A']);scene_cfg=scene.event_configuration(cfg,960)
        bound=bind_household(e['context'],case,MANIFEST);bound['events']=[scene_cfg['event']]
        c=prepare(bound,scene_cfg);g,declared=scene.root_catalogue(c,scene_cfg)
        self.assertEqual(A,e['context']['A']);self.assertEqual(A,bound['A'])
        found=None
        for cell in declared:
            if cell['family']!='ac' or not cell['admissible_raw_alternatives'] or json.loads(cell['label'])[0]!='event_setpoint':continue
            r=scene.complete_cell(c,scene_cfg,g,cell)
            if r is not None:found=r;break
        self.assertIsNotNone(found)
        B=apply(A,found['patches'])
        self.assertEqual([],plan_errors(bound,B))
        self.assertTrue(replay(e['problem'],bound,A,NATIVE)['passed'])
        self.assertTrue(replay(e['problem'],bound,B,NATIVE)['passed'])
        modified=[r for p in found['patches'] for r in p.get('rows',[])]
        self.assertTrue(found['patches'])
        # Original non-AC services survive exactly; event changes do not create
        # appliance actions, new occupants, shortened programmes or EV pauses.
        self.assertEqual({r['task_id']:r for r in A['tasks']},{r['task_id']:r for r in B['tasks']})
        self.assertEqual(sorted((r for r in A['controls'] if r['kind']!='ac_setpoint'),key=digest),
                         sorted((r for r in B['controls'] if r['kind']!='ac_setpoint'),key=digest))
        self.assertTrue(all(960<=p['start_min']<p['end_min']<=1020 for p in found['patches'] if p['type']=='control_interval'))

class SceneAllocationTests(unittest.TestCase):
    def exercise(self,third_slot=False,protect_base=False):
        dates=[f'2007-07-{18+i:02}' for i in range(10)]
        old=[dict(id='old'+str(i),date=d,raw_root_cells=['a'] if i==0 else ['b'] if i==1 else [],
                  tokens=['keep'] if i==2 and protect_base else ['base']) for i,d in enumerate(dates)]
        extras=[]
        for i in (0,1):
            for key in ('a','b','c'):
                extras.append(dict(id=f'alt{i}{key}',date=dates[i],raw_root_cells=[key],tokens=['base']))
        if third_slot:extras.append(dict(id='third-c',date=dates[2],raw_root_cells=['c'],tokens=['base']))
        raw={'role':{k:{'CN'} for k in ('a','b','c')}}
        slots={(0,r['date']):dict(index=0,role='role',country='CN',row=r) for r in old}
        state=dict(rows=[dict(index=0,role='role',country='CN')],raw=raw,slots=slots,
                   required={0:{'base','keep'} if protect_base else {'base'}})
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'candidates').mkdir()
            write_gzip(root/'candidates/0000.json.gz',dict(index=0,rows=extras))
            with patch('benchmark.ab_generation.cohort_coverage.state_from_ledger',return_value=state),\
                 patch.object(scene,'catalogues_with_extras',return_value=[dict(rows=old)]),\
                 patch.object(scene,'simple_tokens',side_effect=lambda r:set(r['tokens'])):
                result=scene.allocate(root,root,deterministic_time=1)
            selected=load(root/'ALLOCATION.json.gz') if (root/'ALLOCATION.json.gz').exists() else []
            return result,selected
    def test_three_disjoint_targets_cannot_fit_two_available_slots(self):
        result,selected=self.exercise()
        self.assertEqual('INFEASIBLE',result['status']);self.assertEqual([],selected)
    def test_third_slot_closes_gap_without_adding_questions(self):
        result,selected=self.exercise(third_slot=True)
        self.assertIn(result['status'],('FEASIBLE','OPTIMAL'))
        self.assertEqual(10,len(selected));self.assertEqual(10,len({r['row']['date'] for r in selected}))
        self.assertEqual({'a','b','c'},{k for r in selected for k in r['row']['raw_root_cells']})
    def test_coverage_never_erases_existing_household_basic_token(self):
        result,_=self.exercise(third_slot=True,protect_base=True)
        self.assertEqual('INFEASIBLE',result['status'])

if __name__=='__main__':unittest.main()
