"""Public integration and counterexamples; contains no survey microdata or labels."""
from pathlib import Path
from copy import deepcopy
from contextlib import redirect_stdout
from collections import Counter
import io,json,os,subprocess,sys,tempfile,unittest
from .fixtures import make_pool
from .pipeline import generate,verify,read_rows,population
from .quotas import plan,largest_remainder,EB_COUNTS
from .cards import render
from ..required_controls import validate_household

class ReusableGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='eb-public-generator-');cls.root=Path(cls.tmp.name)
        cls.config=json.loads((Path(__file__).parent/'configs/pilot96.json').read_text())
        cls.cf=cls.root/'config.json';cls.cf.write_text(json.dumps(cls.config));cls.out=cls.root/'run'
        with redirect_stdout(io.StringIO()):
            make_pool(cls.root/'pool',40)
            cls.manifest=generate(cls.root/'pool/candidate_pool.jsonl',cls.cf,cls.out)
        cls.cases=read_rows(cls.out/'household_cases.jsonl')
        cls.baseline={c['case_id']:c for c in read_rows(cls.out/'selected_cohort.jsonl')}
        q=json.loads((cls.out/'QUOTAS.json').read_text());cls.quotas=(q['country_counts'],q['role_counts'],q['country_role_quotas'])
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_exact_EB_1000_role_totals(self):
        self.assertEqual(largest_remainder(1000,EB_COUNTS),dict(zip('ABCDEF',[166,198,125,151,156,204])))
    def test_full_public_cohort_is_marked_invented(self):
        self.assertTrue(self.manifest['synthetic_fixture_only']);self.assertFalse(self.manifest['raw_sources_independently_checked'])
        self.assertEqual(len(self.cases),96)
        self.assertEqual({c['source']['dataset'] for c in self.cases},{'SYNTHETIC'})
        self.assertEqual(self.manifest['actual_AB_questions']+self.manifest['actual_physical_results']+self.manifest['actual_human_answers'],0)
        self.assertEqual(len({(c['source']['dataset'],c['source']['household_key']) for c in self.cases}),96)
    def test_independent_process_verifies_and_byte_replays(self):
        env=os.environ.copy();repo=Path(__file__).resolve().parents[3]
        env['PYTHONPATH']=str(repo)+os.pathsep+env.get('PYTHONPATH','');env['OMP_NUM_THREADS']='1';env['OPENBLAS_NUM_THREADS']='1'
        result=subprocess.run([sys.executable,'-B','-m','benchmark.household_stage1.generator','verify',str(self.out)],cwd=self.root,env=env,text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(json.loads(result.stdout.splitlines()[-1])['final_replay_byte_identical'])
    def test_observed_source_tamper_rejected(self):
        rows=deepcopy(self.cases);rows[0]['household_size']['value']+=1
        with self.assertRaisesRegex(ValueError,'NORMALIZED_SOURCE_FACT_CHANGED'):
            population(rows,self.baseline,self.config,*self.quotas)
    def test_missing_AC_rejected(self):
        c=deepcopy(self.cases[0]);c['household']['control_inventory']['AC']['enabled']=False
        with self.assertRaises((ValueError,AssertionError)):validate_household(c)
    def test_nonfull_pair_target_independently_checked(self):
        cfg=deepcopy(self.config);cfg['coverage']['nonfull_pair_minimum']=999
        with self.assertRaisesRegex(ValueError,'NONFULL_PAIR_COVERAGE'):
            population(self.cases,self.baseline,cfg,*self.quotas)
    def test_existing_output_is_never_overwritten(self):
        before=(self.out/'MANIFEST.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'OUTPUT_EXISTS'):
            generate(self.root/'pool/candidate_pool.jsonl',self.cf,self.out)
        self.assertEqual(before,(self.out/'MANIFEST.json').read_bytes())
    def test_input_pool_duplicate_source_rejected(self):
        source=read_rows(self.root/'pool/candidate_pool.jsonl');source.append(deepcopy(source[0]));p=self.root/'duplicate.jsonl'
        p.write_text(''.join(json.dumps(c)+'\n' for c in source))
        with self.assertRaisesRegex(ValueError,'INPUT_POOL_CONTAINS_DUPLICATE_SOURCE_RECORDS'):
            generate(p,self.cf,self.root/'duplicate-output')
    def test_mixed_survey_and_synthetic_pool_rejected(self):
        source=read_rows(self.root/'pool/candidate_pool.jsonl');source[0].pop('synthetic_fixture');p=self.root/'mixed.jsonl'
        p.write_text(''.join(json.dumps(c)+'\n' for c in source))
        with self.assertRaisesRegex(ValueError,'SYNTHETIC_AND_SURVEY_RECORDS_MUST_NOT_MIX'):
            generate(p,self.cf,self.root/'mixed-output')
    def test_insufficient_pool_saves_honest_failure_ledger(self):
        source=read_rows(self.root/'pool/candidate_pool.jsonl')[:3];p=self.root/'short.jsonl';p.write_text(''.join(json.dumps(c)+'\n' for c in source));out=self.root/'short'
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(ValueError,'SOURCE_ROLE_SELECTION_SHORTFALL'):
            generate(p,self.cf,out)
        ledger=json.loads((out/'SELECTION_FAILURE.json').read_text())
        self.assertFalse(ledger['is_proof_of_global_infeasibility']);self.assertFalse((out/'MANIFEST.json').exists())
    def test_freeze_detects_changed_file(self):
        p=self.out/'ordinals.json';old=p.read_bytes()
        try:
            p.write_bytes(old+b' ')
            with self.assertRaisesRegex(ValueError,'FROZEN_RUN_FILE_CHANGED'):verify(self.out)
        finally:p.write_bytes(old)
    def test_noninteger_and_inconsistent_quotas_fail(self):
        cfg=deepcopy(self.config);cfg['country_counts']={c:12 for c in cfg['countries']};cfg['country_counts']['CN']=12.0
        with self.assertRaisesRegex(ValueError,'NONNEGATIVE_INTEGERS'):plan(cfg)
        cfg=deepcopy(self.config);cfg['households']=6
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_SIZE'):plan(cfg)
    def test_complete_cards_include_seven_days_and_provenance(self):
        with redirect_stdout(io.StringIO()):p=render(self.out)
        text=p.read_text();self.assertEqual(text.count('### 周日参考安排'),96)
        self.assertIn('本卡没有真实同户调查事实',text);self.assertIn('完整字段来源台账',text)
    def test_service_contracts_do_not_fabricate_events(self):
        for c in self.cases:
            for contract in c['household']['service_contracts'].values():
                self.assertFalse(contract['actual_event_instantiated']);self.assertTrue(contract['require_actual_service_need'])
                if contract['function']=='DR':self.assertTrue(contract['predecessor']['unresolved_predecessor_blocks_instantiation'])
                if contract['function']=='EV':self.assertEqual(contract['operation_policy'],'single_contiguous_session_per_episode')

if __name__=='__main__':unittest.main()
