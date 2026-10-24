import copy
import itertools
from pathlib import Path
import unittest
from unittest.mock import patch

from benchmark.ab_generation.common import read,digest
from benchmark.ab_generation.unified import candidates
from benchmark.ab_generation.unified.contract import config
from benchmark.ab_generation.unified.ipog import generate,interactions
from benchmark.ab_generation.unified.independent import audit
from benchmark.ab_generation.model import apply
from .column_order_protocol import reorder_search,completed_group_base,available_reverse_job
from .shared_domain_comparison import ARMS


class ColumnOrderTests(unittest.TestCase):
    def test_complete_group_identity_not_success_controls_readiness(self):
        record={'household_id':'h','date':'2025-01-01'};cfg={'seed':0};group=Path('/tmp/fixed-comparison-group').resolve()
        rows=[dict(arm=name,seed=0,household_id='h',date=record['date'],
            path=str(group/(name+'.json.gz')),independent_errors=9,status='diagnostic') for name,_ in ARMS]
        self.assertEqual(str(group/'ipog_base.json.gz'),completed_group_base(rows,record,cfg,group))
        for invalid in [rows[:-1],rows[:-1]+[rows[0]],[{**r,'seed':1} for r in rows]]:
            with self.assertRaises(ValueError):completed_group_base(invalid,record,cfg,group)

    def test_group_barrier_passes_identical_fixed_task_to_worker(self):
        group=Path('/tmp/group').resolve()
        task=({'household_id':'h','date':'2025-01-01'},{'seed':0},str(group/'ipog_base.json.gz'),'/tmp/order','core')
        rows=[dict(arm=name,seed=0,household_id='h',date='2025-01-01',path=str(group/(name+'.json.gz'))) for name,_ in ARMS]
        with patch('benchmark.research_delivery.column_order_protocol.code_hash',return_value='core'), \
             patch('benchmark.research_delivery.column_order_protocol.Path.exists',return_value=True), \
             patch('benchmark.research_delivery.column_order_protocol.read',return_value=rows), \
             patch('benchmark.research_delivery.column_order_protocol.reverse_job',return_value={'done':True}) as worker:
            self.assertEqual({'done':True},available_reverse_job(task))
            worker.assert_called_once_with(task)

    def test_all_targets_and_witnesses_map_to_original_axes(self):
        domains=[[0,1],[0,1,2],[0,1],[0,1]]
        full=[list(x) for x in itertools.product(*domains) if not(x[0] and x[1]==2)]
        def oracle(p):
            w=next((r for r in full if all(r[i]==v for i,v in p.items())),None)
            return ('feasible',w,'literal') if w else ('infeasible',None,'literal')
        for perm in ([0,1,2,3],[3,1,0,2]):
            result=reorder_search(generate,perm)(domains,oracle,triples=[(0,2,3)])
            self.assertTrue(result['complete'])
            self.assertEqual(set(interactions(domains,[(0,2,3)])),{tuple(map(tuple,r['target'])) for r in result['coverage']})
            for target in result['coverage']:
                exists=any(all(row[i]==v for i,v in target['target']) for row in full)
                self.assertEqual(exists,target['witness_row'] is not None)
                if exists:
                    witness=result['rows'][target['witness_row']]
                    self.assertIn(witness,full);self.assertTrue(all(witness[i]==v for i,v in target['target']))

    def test_identity_wrapper_keeps_whole_actual_pipeline_result(self):
        c=read(Path(__file__).parents[1]/'ab_generation/examples/control.json')
        c['reference']['thermal']={};c['reference']['information_set']['mode']='offline_unexecuted_A_plan'
        cfg=config(dict(rows_per_unit=2,queries_per_row=2,ac_delta_C=[.5],tank_delta_C=[1],
                        thermal_duration_min=[10],precondition_min=[10],oracle_propagation='interval_forward_v1',
                        mechanism_joint_extension=True))
        prepared=candidates.prepare(c,cfg);grammar=candidates.catalogue_domains(prepared,cfg)
        with patch.object(candidates,'catalogue_domains',return_value=grammar):base=candidates.generate_day(c,cfg)
        with patch.object(candidates,'catalogue_domains',return_value=grammar), \
             patch.object(candidates,'generate',reorder_search(candidates.generate,list(range(len(grammar['domains']))))):
            identity=candidates.generate_day(c,cfg)
        self.assertEqual(digest(base),digest(identity))
        with patch.object(candidates,'catalogue_domains',return_value=grammar), \
             patch.object(candidates,'generate',reorder_search(candidates.generate,list(reversed(range(len(grammar['domains'])))))):
            reverse=candidates.generate_day(c,cfg)
        self.assertEqual(base['native_domains'],reverse['native_domains'])
        self.assertEqual(base['mechanism_probes'],reverse['mechanism_probes'])
        for row in reverse['rows']:self.assertEqual([],audit(prepared,prepared['A'],apply(prepared['A'],row['patches'])))


if __name__=='__main__':unittest.main()
