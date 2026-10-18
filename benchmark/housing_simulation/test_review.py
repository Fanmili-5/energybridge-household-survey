"""Regression cases for contract/evidence gaps found in the whole-line review."""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import shutil
import unittest

from .assembly import assemble
from .pipeline import read, save, seal, sha
from . import test_assembly as fixture_module
from .validation import audit, check_baseline
from .weather import inspect_weather


class ContractReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_module.WorldAssemblyTests.setUpClass()
        cls.fixture=fixture_module.WorldAssemblyTests()

    @classmethod
    def tearDownClass(cls):fixture_module.WorldAssemblyTests.tearDownClass()

    def test_sleep_and_bath_require_assigned_rooms(self):
        for activity,selector,message in [('sleep','$living','assigned bedroom'),('bath','$living','sanitary room')]:
            with self.subTest(activity=activity):
                s=self.fixture.spec()
                event=next(e for e in s['calendars']['adult1']['weekday']if e['activity']==activity)
                event['room']=selector
                with self.assertRaisesRegex(ValueError,message):self.fixture.pack(s)

    def test_nap_cannot_authorize_handling(self):
        s=self.fixture.spec();e=next(e for e in s['calendars']['adult1']['weekday']if e['available_for_operation'])
        e.update(activity='nap',room='$sleep')
        with self.assertRaisesRegex(ValueError,'invalid operation availability'):self.fixture.pack(s)

    def test_hot_water_requires_asset_access(self):
        s=self.fixture.spec(2)
        tank=next(d for d in s['devices']if d['kind']=='water_heater');tank['using_household_ids']=[s['household_id']]
        for m in s['members']:
            if m['household_id']!=s['household_id']:
                m['can_operate_asset_ids']=[a for a in m['can_operate_asset_ids']if a!=tank['asset_id']]
        with self.assertRaisesRegex(ValueError,'hot-water asset access'):self.fixture.pack(s)

    def test_B_controls_require_target_household_authority(self):
        s=self.fixture.spec()
        for m in s['members']:
            if 'ac'in m['can_operate_asset_ids']:m['can_operate_asset_ids'].remove('ac')
        with self.assertRaisesRegex(ValueError,'lacks control authority'):self.fixture.pack(s)

    def test_multiple_independent_ACs_in_one_zone_rejected(self):
        s=self.fixture.spec();d=copy.deepcopy(next(d for d in s['devices']if d['kind']=='ac'));d['asset_id']='ac2';s['devices'].append(d)
        c=copy.deepcopy(s['controls'][0]);c['asset_id']='ac2';s['controls'].append(c)
        with self.assertRaisesRegex(ValueError,'one independently controlled AC'):self.fixture.pack(s)

    def test_EV_control_cannot_span_two_connections(self):
        s=self.fixture.spec();s['controls']=[c for c in s['controls']if c['kind']!='ev_charge_window']+[{'asset_id':'ev','kind':'ev_charge_window','start_min':0,'end_min':1440,'stop_at_target_soc':.7}]
        with self.assertRaisesRegex(ValueError,'one physical overnight connection'):self.fixture.pack(s)

    def test_EV_reserve_checked_for_full_baseline(self):
        s=self.fixture.spec();next(d for d in s['devices']if d['kind']=='ev')['parameters']['initial_energy_kwh']=7
        s['controls']=[c for c in s['controls']if c['kind']!='ev_charge_window']
        with self.assertRaisesRegex(ValueError,'minimum reserve'):self.fixture.pack(s)

    def test_EV_anchor_unplug_requires_available_handler(self):
        s=self.fixture.spec();events=copy.deepcopy(s['calendars']['adult1']['weekday'])
        for e in events:
            if e['start_min']==420:e['available_for_operation']=False
        s['calendars']['adult1']['date_overrides']={s['anchor']:events}
        pack,pairs=self.fixture.pack(s)
        with self.assertRaisesRegex(ValueError,'BASELINE_NOT_EXECUTABLE'):check_baseline(pack,pairs,self.fixture.job['settings'])

    def test_weather_registration_and_annual_coverage(self):
        source=self.fixture.job['weather_source'];weather=self.fixture.weather
        self.assertEqual(inspect_weather(weather,source)['hours'],8760)
        with self.assertRaisesRegex(ValueError,'WEATHER_IDENTITY'):inspect_weather(weather,{**source,'sha256':'0'*64})
        with tempfile.TemporaryDirectory()as t:
            p=Path(t)/'zero-minute.epw';rows=weather.read_text().splitlines()
            for i in range(8,len(rows)):
                fields=rows[i].split(',');fields[4]='0';rows[i]=','.join(fields)
            p.write_text('\n'.join(rows)+'\n')
            self.assertEqual(inspect_weather(p,{**source,'sha256':sha(p)})['hourly_minute_label'],0)
            p=Path(t)/'short.epw';p.write_text('\n'.join(weather.read_text().splitlines()[:-1])+'\n')
            with self.assertRaisesRegex(ValueError,'WEATHER_COVERAGE'):inspect_weather(p,{**source,'sha256':sha(p)})

    def test_traceability_rejects_broken_anchor_and_unmapped_field(self):
        from .pipeline import HERE
        from .provenance import check_links
        for defect,message in [('anchor','missing document anchor'),('field','unmapped schema property')]:
            with self.subTest(defect=defect), tempfile.TemporaryDirectory()as t:
                root=Path(t)/'package';shutil.copytree(HERE,root,ignore=shutil.ignore_patterns('__pycache__'))
                if defect=='anchor':
                    value=read(root/'RULES.json');value['rules'][0]['documentation']='METHOD.md#missing-anchor';save(root/'RULES.json',value)
                else:
                    value=read(root/'WORLD.schema.json');value['properties']['unregistered']={'type':'string'};save(root/'WORLD.schema.json',value)
                with self.assertRaisesRegex(ValueError,message):check_links(root)

    def test_weather_mismatch_fails_before_world_output(self):
        with tempfile.TemporaryDirectory()as t:
            p=Path(t)/'job.json';job=copy.deepcopy(self.fixture.job);job['weather_source']['sha256']='0'*64;save(p,job)
            with self.assertRaisesRegex(ValueError,'WEATHER_IDENTITY'):assemble(p,self.fixture.shells,self.fixture.weather,Path(t)/'out')
            self.assertFalse((Path(t)/'out').exists())


class ReadbackReviewTests(unittest.TestCase):
    def fixture(self,root,change=None):
        compiled=root/'compiled';runs=root/'runs';times=list(range(0,12960,10))
        base={'source_shell_sha256':'0'*64,'weather_sha256':'1'*64,'history_days':7,'run_interval_min':[-10080,12960],
              'intervention_last_request_min':1920,'world_assembly':{'room_ids':['room'],'tank_nodes':2,'electrical_supply_W':1000},
              'tank_name':'TANK','hot_water_model':'standalone_hot_outlet','EV':{'installed':False},'HVAC_equipment_mapping':{},
              'equipment_meter_mapping':{'WASHER':{'asset_id':'washer','kind':'washer','watts':500}},
              'execution':{'tasks':[{'asset_id':'washer','kind':'washer','start_min':600,'end_min':660}],
                           'batches':[{'need_id':'wash','program_executed':True,'collected':True,'requested_program_end_min':660,'requested_retrieval_end_min':680}],
                           'operation_failures':{},'dropped_program_ids':[]},
              'service_needs':[{'need_id':'wash','release_min':500,'deadline_min':1000}],
              'water_needs':[{'need_id':'bath','release_min':720,'deadline_min':730,'quantity':10,'minimum_C':40}]}
        trace={}
        def channel(name,key,unit,fn,meter=False):trace[name+'|'+key]={'unit':unit,'is_meter':meter,'values':[[t,fn(t)]for t in times]}
        active=lambda t:300000 if 600<=t<660 else 0
        for name in ['Electricity:Facility','InteriorEquipment:Electricity']:channel(name,'','J',active,True)
        for name in ['Electricity:HVAC','InteriorLights:Electricity','WaterSystems:Electricity']:channel(name,'','J',lambda t:0,True)
        channel('Electric Equipment Electricity Energy','WASHER','J',active)
        for name in ['Zone Mean Air Temperature','Zone Mean Radiant Temperature']:channel(name,'ROOM','C',lambda t:25)
        channel('Zone Air Relative Humidity','ROOM','%',lambda t:50)
        channel('Zone People Occupant Count','ROOM','',lambda t:1)
        for name in ['Water Heater Tank Temperature','Water Heater Use Side Outlet Temperature','Water Heater Final Temperature Node 1','Water Heater Final Temperature Node 2']:channel(name,'TANK','C',lambda t:55)
        channel('Water Heater Use Side Mass Flow Rate','TANK','kg/s',lambda t:10/600 if t==720 else 0)
        results=[]
        for side in ('A','B'):
            meta=copy.deepcopy(base);tr=copy.deepcopy(trace)
            if change:change(meta,tr)
            model=compiled/'case'/side/'model.idf';model.parent.mkdir(parents=True);model.write_text('synthetic audit fixture;')
            meta['idf_sha256']=sha(model);save(model.parent/'INPUT.json.gz',meta)
            folder=runs/'case'/side;save(folder/'TRACE.json.gz',tr);(folder/'out').mkdir();(folder/'out/eplusout.sql').write_bytes(b'synthetic receipt only')
            result={'status':'completed','idf_sha256':sha(model),'trace_sha256':sha(folder/'TRACE.json.gz'),'SQL_sha256':sha(folder/'out/eplusout.sql')};save(folder/'RESULT.json',result);results.append(result)
        seal(compiled,{'records':[{'id':'case','status':'compiled'}]});seal(runs,{'records':results,'compiled_manifest_sha256':sha(compiled/'MANIFEST.json')})
        return audit(compiled,runs,root/'audit')

    def test_complete_contract_passes(self):
        with tempfile.TemporaryDirectory()as t:self.assertTrue(self.fixture(Path(t))['passed'])

    def test_feasible_trip_does_not_hide_departure_target_shortfall(self):
        def change(meta, trace):
            meta['EV'] = {'installed': True, 'energy_balance_error_kWh': 0,
                          'stop_at_unexecutable_trip_min': None, 'end_energy_kWh': 42,
                          'trips': [{'unserved_traction_kWh': 0, 'minimum_reserve_shortfall_kWh': 0,
                                     'target_shortfall_kWh': 1}]}
            meta['EV_grid_steps'] = []
            values = [[t, 0] for t, _ in trace['Electricity:Facility|']['values']]
            for name in ('ExteriorEquipment:Electricity|', 'Exterior Equipment Electricity Energy|EXTERNAL_EV'):
                trace[name] = {'unit': 'J', 'is_meter': name.startswith('ExteriorEquipment:'), 'values': values}
        with tempfile.TemporaryDirectory() as temp:
            result = self.fixture(Path(temp), change)
            self.assertFalse(result['passed'])
            self.assertTrue(result['records'][0]['checks']['B_EV_balance'])
            self.assertFalse(result['records'][0]['checks']['B_EV_departure_target'])

    def test_independent_comfort_is_checked_and_unknown_is_preserved(self):
        for band in ([26, 27], None):
            def change(meta, trace):
                meta['comfort_requirements'] = [{'need_id': 'comfort', 'room_id': 'room', 'release_min': 480,
                                                'deadline_min': 1920, 'temperature_band_C': band}]
            with self.subTest(band=band), tempfile.TemporaryDirectory() as temp:
                result = self.fixture(Path(temp), change)
                if band:
                    self.assertFalse(result['passed'])
                    self.assertFalse(result['records'][0]['checks']['B_declared_comfort'])
                else:
                    self.assertTrue(result['passed'])
                    self.assertEqual('unknown', result['records'][0]['details']['B_independent_comfort']['status'])

    def test_missing_zone_channel_in_both_arms_cannot_pass(self):
        with tempfile.TemporaryDirectory()as t:
            result=self.fixture(Path(t),lambda m,tr:tr.pop('Zone Mean Air Temperature|ROOM'))
            self.assertFalse(result['passed']);self.assertIn('required physical channel missing',result['records'][0]['details']['reason'])

    def test_missing_tank_node_in_both_arms_cannot_pass(self):
        for name in ('Water Heater Tank Temperature','Water Heater Final Temperature Node 2'):
            with self.subTest(channel=name),tempfile.TemporaryDirectory()as t:
                self.assertFalse(self.fixture(Path(t),lambda m,tr:tr.pop(name+'|TANK'))['passed'])

    def test_missing_service_batch_cannot_pass(self):
        with tempfile.TemporaryDirectory()as t:
            result=self.fixture(Path(t),lambda m,tr:m['execution'].update(batches=[]))
            self.assertFalse(result['passed']);self.assertFalse(result['records'][0]['checks']['A_service_completeness'])

    def test_completed_service_keeps_its_deadline_beyond_run_boundary(self):
        def extend(meta, trace):
            meta['service_needs'][0]['deadline_min'] = meta['run_interval_min'][1] + 1440
            meta['execution']['tasks'][0]['need_id'] = 'wash'
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(self.fixture(Path(temp), extend)['passed'])

    def test_wrong_units_cannot_pass(self):
        with tempfile.TemporaryDirectory()as t:
            result=self.fixture(Path(t),lambda m,tr:tr['Zone Mean Air Temperature|ROOM'].update(unit='K'))
            self.assertFalse(result['passed']);self.assertIn('unit mismatch',result['records'][0]['details']['reason'])


if __name__=='__main__':unittest.main()
