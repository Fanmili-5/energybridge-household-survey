import copy
from pathlib import Path
import tempfile
import unittest

from benchmark.ab_generation.common import read,save,digest
from benchmark.ab_generation.unified.contract import config
from benchmark.ab_generation.unified.pipeline import _job
from .shared_domain_comparison import group_job,read_catalogue


class SharedDomainTests(unittest.TestCase):
    def test_cached_arms_equal_independent_full_generation_and_relocation(self):
        fixture=Path(__file__).parents[1]/'ab_generation/examples/control.json'
        c=read(fixture);c['reference']['thermal']={};c['reference']['information_set']['mode']='offline_unexecuted_A_plan'
        for n in c['needs']:
            if n['kind']=='washer':n.update(maximum_preload_wait_min=110,maximum_retrieval_wait_min=150)
            if n['kind']=='dishwasher':n.update(deadline_min=1300,maximum_preload_wait_min=20,maximum_retrieval_wait_min=30)
        cfg=config(dict(method_revision='delivery_v2_8',handling_calendar_domain='include_life_conflicts',
            oracle_propagation='interval_forward_v1',mechanism_joint_extension=True,opportunity_bounds='precedence_v1',
            rows_per_unit=2,queries_per_row=2,oracle_native_encoding_budget=128,
            ac_delta_C=[.5],tank_delta_C=[1],thermal_duration_min=[10],precondition_min=[10]))
        arms=(('base',{}),('larger',{'rows_per_unit':4}))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);save(root/'context.json',c);save(root/'portrait.json',{})
            item=dict(household_id=c['household_id'],date=c['date'],context_path=str(root/'context.json'),portrait_path=str(root/'portrait.json'))
            rows=group_job((item,cfg,str(root/'group'),arms))
            self.assertEqual(2,len(rows))
            for arm,change in arms:
                cached=read_catalogue(root/'group'/(arm+'.json.gz'));fresh=_job((item,config({**cfg,**change})))
                for key in ('comparison','shared_native_domain','telemetry'):cached.pop(key,None);fresh.pop(key,None)
                self.assertEqual(digest(fresh),digest(cached))
            import shutil
            shutil.copytree(root/'group',root/'moved group')
            self.assertEqual(digest(read_catalogue(root/'group/base.json.gz')),digest(read_catalogue(root/'moved group/base.json.gz')))
            shared=root/'moved group/NATIVE_DOMAIN.json.gz';data=read(shared);data['factors']=[];save(shared,data)
            with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):read_catalogue(root/'moved group/base.json.gz')


if __name__=='__main__':unittest.main()
