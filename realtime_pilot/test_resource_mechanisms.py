import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from common import STUDY,file_hash,digest
from resource_versions import freeze,resolve_catalog
import simulation_environment as env
from date_sampling import candidates,sample,GROUPS
sys.path.insert(0,str(STUDY/'scripts'))
from validation_cache import reusable

class MechanismTests(unittest.TestCase):
    def test_cache_invalidates_ddy_engine_code_and_unversioned_report(self):
        m={'sha256':'idf'};w={'epw_sha256':'epw','ddy_sha256':'ddy'}
        row={'passed':True,'model_sha256':'idf','weather_sha256':'epw','localization':{'design_days_sha256':'ddy'}}
        context={'files':{'engine':'A','code':'B'}}
        self.assertTrue(reusable(row,m,w,context,context))
        self.assertFalse(reusable(row,m,{**w,'ddy_sha256':'new'},context,context))
        for changed in ({'files':{'engine':'new','code':'B'}},{'files':{'engine':'A','code':'new'}},None):
            self.assertFalse(reusable(row,m,w,changed,context))
        self.assertFalse(reusable({**row,'passed':False},m,w,context,context))

    def test_old_physical_inputs_survive_catalog_update_and_are_not_substituted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'simulation_resources';resources.mkdir()
            for name in ('model.idf','weather.epw','design.ddy'):(resources/name).write_text(name)
            m={'id':'m','idf':'simulation_resources/model.idf','sha256':file_hash(resources/'model.idf'),'status':'verified'}
            w={'id':'w','epw':'simulation_resources/weather.epw','epw_sha256':file_hash(resources/'weather.epw'),'ddy':'simulation_resources/design.ddy','ddy_sha256':file_hash(resources/'design.ddy'),'status':'verified'}
            c={'models':[m],'weather':[w],'validated_dates':{'m|w':['2007-07-01']}}
            path=resources/'catalog.json';path.write_text(json.dumps(c));version=freeze(path)
            self.assertEqual(freeze(path),version)
            e={'version':env.VERSION,'resource_catalog_sha256':version,'building':m,'weather':w,'simulation_start_date':'2007-07-01'};e['environment_hash']=digest(e)
            path.write_text(json.dumps({**c,'new_metadata':True}));(resources/'weather.epw').write_text('new weather')
            with patch.object(env,'CATALOG',path):
                files=env.verify(e);self.assertEqual(files[1].read_text(),'weather.epw')
                files[1].write_text('tampered')
                with self.assertRaises(ValueError):env.verify(e)
            with self.assertRaises(ValueError):resolve_catalog(path,'../escape')

    def test_dates_cover_strata_freeze_seed_and_exclude_unvalidated_days(self):
        epw=STUDY/env.catalog()['weather'][0]['epw']
        rows=candidates(epw,'audit',3)
        self.assertEqual(len(rows),9);self.assertEqual({r['stratum'] for r in rows},set(GROUPS))
        pool=[r['date'] for r in rows]
        self.assertEqual(sample(epw,pool,'same'),sample(epw,pool,'same'))
        seen=set()
        for i in range(90):
            day,meta=sample(epw,pool,str(i));self.assertIn(day,pool);seen.add(meta['stratum'])
            self.assertAlmostEqual(meta['conditional_date_probability'],1/9)
        self.assertEqual(seen,set(GROUPS))
        day,meta=sample(epw,[pool[0]],'single');self.assertEqual(day,pool[0]);self.assertEqual(meta['conditional_date_probability'],1)
        self.assertEqual(len(meta['missing_strata']),2)
        with self.assertRaises(ValueError):sample(epw,['2007-01-01'],'wrong-season')
        for season in ('winter','spring','autumn'):
            self.assertEqual(len(candidates(epw,'audit',3,season)),9)
