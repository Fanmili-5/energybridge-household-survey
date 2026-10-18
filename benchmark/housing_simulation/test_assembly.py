"""Nonempty public worlds and failure cases; no historical household inputs."""
import copy
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .assembly import assemble, bind_world, build_pack, make_pair
from .pipeline import HERE, build_shell, compile_pairs, read, save, sha, verify
from .validation import check_baseline


class WorldAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.shells=cls.root/'shells';build_shell(HERE/'examples/shell_batch.json',cls.shells)
        cls.job=read(HERE/'examples/world_batch.json')
        # Invented complete annual fixture; never used for EnergyPlus validation.
        cls.weather=cls.root/'test.epw'
        header='LOCATION,Invented,Test,ZZZ,Synthetic,000000,0,0,0,0\nDESIGN CONDITIONS,0\nTYPICAL/EXTREME PERIODS,0\nGROUND TEMPERATURES,0\nHOLIDAYS/DAYLIGHT SAVING,No,0,0,0\nCOMMENTS 1,Invented\nCOMMENTS 2,Unit fixture\nDATA PERIODS,1,1,Data,Wednesday,1/1,12/31\n'
        rows=[]
        for i in range(8760):
            d=dt.datetime(2025,1,1)+dt.timedelta(hours=i)
            row=[2025,d.month,d.day,d.hour+1,60,'?',20,10,50,101325]+[0]*25
            rows.append(','.join(map(str,row))+'\n')
        cls.weather.write_text(header+''.join(rows))
        cls.job['weather_source']={'provider':'Invented unit fixture','url':'https://example.invalid/epw','dataset':'synthetic','release':'v1','sha256':sha(cls.weather),'station':'000000'}


    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def spec(self,index=1):return copy.deepcopy(self.job['households'][index])

    def pack(self,spec):
        layout=read(self.shells/spec['household_id']/'layout.json')
        world=bind_world(spec,layout)
        pack,states=build_pack(spec,world,self.shells/spec['household_id']/'shell.idf',sha(self.weather))
        pairs=[make_pair(c,spec,pack,states)for c in spec['cases']]
        return pack,pairs

    def test_nonempty_arbitrary_batch_and_shared_roster(self):
        with tempfile.TemporaryDirectory()as t:
            for count in (1,3):
                job=copy.deepcopy(self.job);job['households']=job['households'][:count];p=Path(t)/f'job{count}.json';save(p,job)
                out=Path(t)/str(count);result=assemble(p,self.shells,self.weather,out)
                self.assertEqual([r['status']for r in result['records']],['assembled']*count)
                for h in job['households']:
                    world=read(out/'households'/h['household_id']/'world.json')
                    self.assertTrue(world['layout']['complete_household_energy_world'])
                    self.assertEqual(len(world['parameter_pack']['devices']),6)
                    self.assertEqual(set(world['sleep_room_by_member']),{m['member_id']for m in h['members']})
                if count==3:
                    world=read(out/'households/example-shared/world.json')
                    self.assertEqual(len(world['members']),4)
                    self.assertIn('neighbor',world['sleep_room_by_member'])
                verify(out)

    def test_missing_shared_roster_rejected(self):
        s=self.spec(2);s['members']=[m for m in s['members']if m['member_id']!='neighbor']
        with self.assertRaisesRegex(ValueError,'complete roster'):self.pack(s)

    def test_duplicate_member_and_incomplete_bed_assignment_rejected(self):
        s=self.spec();s['members'].append(copy.deepcopy(s['members'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate member_id'):self.pack(s)
        s=self.spec();s['sleep_groups']=s['sleep_groups'][:1]
        with self.assertRaisesRegex(ValueError,'exactly one bed'):self.pack(s)

    def test_sleep_area_capacity_and_room_rights(self):
        s=self.spec();s['sleep_groups'][0]['bed_footprint_m']=[20,20]
        with self.assertRaisesRegex(ValueError,'NO_SLEEP_SPACE'):self.pack(s)
        s=self.spec(2);layout=read(self.shells/s['household_id']/'layout.json')
        s['sleep_groups'][0]['room_id']=next(r['room_id']for r in layout['rooms']if r['census_room_class']=='bedroom' and r['using_household_ids']==[s['household_id']+'-aux-01'])
        with self.assertRaisesRegex(ValueError,'NO_SLEEP_SPACE'):self.pack(s)
        s=self.spec();s['sleep_groups'][0]['capacity']=1
        with self.assertRaisesRegex(ValueError,'capacity exceeded'):self.pack(s)

    def test_no_installation_space_retains_household_in_denominator(self):
        job=copy.deepcopy(self.job);job['households'][0]['devices'][0]['footprint_m']=[20,20]
        with tempfile.TemporaryDirectory()as t:
            p=Path(t)/'job.json';save(p,job);r=assemble(p,self.shells,self.weather,Path(t)/'out')
            self.assertEqual(len(r['records']),3);self.assertEqual(r['records'][0]['status'],'rejected')
            self.assertEqual([x['status']for x in r['records'][1:]],['assembled','assembled'])
            self.assertEqual(r['case_count'],2)

    def test_circuit_budget_and_missing_connections_rejected(self):
        s=self.spec();s['electrical_supply_W']=100
        with self.assertRaisesRegex(ValueError,'ELECTRICAL_NAMEPLATE'):self.pack(s)
        s=self.spec();s['devices'][0]['connections']=['electricity']
        with self.assertRaisesRegex(ValueError,'connections incomplete'):self.pack(s)

    def test_operator_age_rights_and_presence(self):
        s=self.spec();s['members'][0]['age_years']=12
        with self.assertRaisesRegex(ValueError,'age16'):self.pack(s)
        s=self.spec();s['members'][0]['can_operate_asset_ids'].remove('washer')
        with self.assertRaisesRegex(ValueError,'not authorized'):self.pack(s)
        s=self.spec();s['services'][0].update(start_min=900,retrieval_min=970,release_min=880)
        pack,pairs=self.pack(s)
        with self.assertRaisesRegex(ValueError,'BASELINE_NOT_EXECUTABLE'):check_baseline(pack,pairs,self.job['settings'])

    def test_calendar_gap_and_shared_bath_collision_rejected(self):
        s=self.spec();s['calendars']['adult1']['weekday'][0]['end_min']=410
        with self.assertRaisesRegex(ValueError,'without gaps'):self.pack(s)
        s=self.spec();s['calendars']['adult2']=copy.deepcopy(s['calendars']['adult1'])
        with self.assertRaisesRegex(ValueError,'overlapping bathroom'):self.pack(s)

    def test_control_type_range_and_notice_boundary(self):
        s=self.spec();s['controls'][0]['cooling_setpoint_C']=18
        with self.assertRaisesRegex(ValueError,'deadband'):self.pack(s)
        s=self.spec();s['cases'][0]['control_overrides'][0]['start_min']=470
        with self.assertRaisesRegex(ValueError,'before notice'):self.pack(s)
        s=self.spec();s['cases'][0]['service_shifts'][0]['shift_min']=-700
        with self.assertRaisesRegex(ValueError,'pre-notice'):self.pack(s)

    def test_baseline_and_pair_are_explicit_and_distinct(self):
        for spec in self.job['households']:
            pack,pairs=self.pack(copy.deepcopy(spec));check_baseline(pack,pairs,self.job['settings'])
            pair=pairs[0];self.assertNotEqual(pair['schedule_hashes']['A'],pair['schedule_hashes']['B'])
            self.assertTrue(pack['HVAC']);self.assertTrue(pack['tasks']);self.assertTrue(pack['journeys'])
            self.assertEqual(set(pair['A']['tasks'][0]),set(pair['B']['tasks'][0]))
            self.assertTrue(0<pair['EV_continuous_reference']['initial_energy_kWh']<=60)

    def test_failed_retrieval_is_not_repaired_and_blocks_following_service(self):
        from .kernel.execution import execute
        s=self.spec(0);s['cases'][0]['service_shifts'][-1]['shift_min']=30
        pack,pairs=self.pack(s);pair=pairs[0];base=(dt.date.fromisoformat(pair['date'])-dt.date.fromisoformat(pack['anchor'])).days*1440
        plan={k:[{**x,'start_min':x['start_min']-base,'end_min':x['end_min']-base}for x in pack[k]if base<=x['start_min']<base+3*1440]for k in ('tasks','operations')}
        for key,ident in [('tasks','task_id'),('operations','operation_id')]:
            replacements={x[ident]:x for x in pair['B'][key]};plan[key]=[x for x in plan[key]if x[ident]not in replacements]+list(replacements.values());plan[key].sort(key=lambda x:x['start_min'])
        result=execute(pack,pair,plan,0,3*1440)
        self.assertFalse(result['automatic_repair'])
        self.assertTrue(any('OPERATOR_UNAVAILABLE'in v for v in result['operation_failures'].values()))
        self.assertTrue(any('ASSET_STILL_OCCUPIED'in b['reasons']for b in result['batches']))

    def test_structural_schema_rejects_unknown_fields_before_output(self):
        with tempfile.TemporaryDirectory()as t:
            p=Path(t)/'job.json';job=copy.deepcopy(self.job);job['households'][0]['unexpected']=True;save(p,job)
            with self.assertRaisesRegex(ValueError,'WORLD_SCHEMA'):assemble(p,self.shells,self.weather,Path(t)/'out')
            self.assertFalse((Path(t)/'out').exists())

    def test_dryer_requires_collected_washer_output(self):
        s=self.spec();s['services'][1].update(start_min=1120,retrieval_min=1180,release_min=1080)
        pack,pairs=self.pack(s)
        with self.assertRaisesRegex(ValueError,'BASELINE_NOT_EXECUTABLE'):check_baseline(pack,pairs,self.job['settings'])

    def test_insufficient_calendar_and_leap_replay_rejected(self):
        s=self.spec();s['cases'][0]['date']='2025-01-02';pack,pairs=self.pack(s)
        with self.assertRaisesRegex(ValueError,'outside supplied calendar'):check_baseline(pack,pairs,self.job['settings'])
        s=self.spec();s['anchor']='2024-01-01';s['end_exclusive']='2025-01-01';s['cases'][0]['date']='2024-03-01';pack,pairs=self.pack(s)
        # Isolate leap-day rejection from the longer public reference history.
        with self.assertRaisesRegex(ValueError,'nonleap'):check_baseline(pack,pairs,{**self.job['settings'],'history_days':7})

    def test_public_worlds_compile_without_engine_or_cohort(self):
        with tempfile.TemporaryDirectory()as t:
            root=Path(t);p=root/'job.json';save(p,self.job);assemble(p,self.shells,self.weather,root/'worlds')
            r=compile_pairs(root/'worlds/physics_job.json',root/'compiled')
            self.assertEqual([x['status']for x in r['records']],['compiled']*3)
            for item in r['records']:
                a=(root/'compiled'/item['id']/'A/model.idf').read_text();b=(root/'compiled'/item['id']/'B/model.idf').read_text()
                self.assertNotEqual(a,b);self.assertIn('WaterHeater:Stratified',a);self.assertIn('ZoneHVAC:PackagedTerminalHeatPump',a)
                self.assertNotIn('Autosize',a)

    def test_cross_process_hash_seed_determinism(self):
        with tempfile.TemporaryDirectory()as t:
            root=Path(t)
            code="from pathlib import Path;from benchmark.housing_simulation.pipeline import *;import sys;build_shell(HERE/'examples/shell_batch.json',Path(sys.argv[1]))"
            for seed in ('1','9157'):
                subprocess.run([sys.executable,'-B','-c',code,str(root/seed)],check=True,env={**os.environ,'PYTHONHASHSEED':seed},capture_output=True,text=True)
            self.assertEqual(read(root/'1/MANIFEST.json')['files'],read(root/'9157/MANIFEST.json')['files'])


if __name__=='__main__':unittest.main()
