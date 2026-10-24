"""Independent small-grid checks for retaining soft handling conflicts."""
import copy
from pathlib import Path
import unittest

from ..common import read, digest
from ..model import apply
from .candidates import program_grammar, legacy_config, numeric_handling_slots, issues
from .contract import config
from .factorized import ProgramRecipe, prepare_template, export, expand
from .independent import audit


class HandlingDomainTests(unittest.TestCase):
    def setUp(self):
        self.c=read(Path(__file__).parents[1]/'examples/control.json')
        self.d=next(d for d in self.c['devices'] if d['asset_id']=='dishes')
        self.n=next(n for n in self.c['needs'] if n['need_id']=='dishes')
        self.n.update(deadline_min=1300,maximum_preload_wait_min=20,maximum_retrieval_wait_min=30)
        self.c['operator_windows']['p1']=[[1110,1120],[1260,1270]]
        self.c['reservations']=[dict(room_id='kitchen',start_min=1080,end_min=1090)]

    def recipes(self,mode='include_life_conflicts'):
        return [r for r in program_grammar(self.c,self.d,legacy_config(config()),mode) if isinstance(r,ProgramRecipe)]

    @staticmethod
    def coordinates(rows):
        return {(r.template['patches'][0]['rows'][0]['start_min'],r.load_min,r.unload_min) for r in rows}

    def test_full_grid_matches_independent_three_coordinate_enumerator(self):
        before=copy.deepcopy(self.c);actual=self.coordinates(self.recipes())
        expected=set()
        # Independent exhaustive bounds over the small fixture, with no calls
        # to the generator's slot function or admission classifier.
        for machine in range(480,1920,10):
            for load in range(1040,1310,10):
                for unload in range(1040,1310,10):
                    if not 1040<=machine<=1220:continue
                    if not 1050<=load or load+10>machine or machine-load-10>20:continue
                    if not machine+90<=unload<=machine+120 or unload+10>1300:continue
                    expected.add((machine,load,unload))
        self.assertEqual(expected,actual)
        old=self.coordinates(self.recipes('convenience_only'))
        self.assertTrue(old<actual)
        self.assertEqual(before,self.c)

    def test_calendar_and_booking_conflict_is_not_engineering_error(self):
        r=next(r for r in self.recipes() if (r.template['patches'][0]['rows'][0]['start_min'],r.load_min,r.unload_min)==(1100,1080,1200))
        checks,gates,_=issues(self.c,r['patches'],['dishes'])
        self.assertIn('OPERATOR_UNAVAILABLE',checks)
        self.assertIn('FACILITY_RESERVED',checks)
        self.assertEqual([],gates)
        self.assertEqual([],audit(self.c,self.c['A'],apply(self.c['A'],r['patches'])))

    def test_qualification_and_immutable_operators_still_mask_movements(self):
        for mode in ('unqualified','immutable'):
            with self.subTest(mode=mode):
                if mode=='unqualified':self.c['authority']['assets']['dishes']['authorized_operator_ids']=[]
                else:
                    self.c['authority']['assets']['dishes']['authorized_operator_ids']=['p1']
                    self.c['authority']['immutable_operator_ids']=['p1']
                rows=self.recipes()
                self.assertTrue(rows)
                self.assertEqual({(1110,1260)},{(r.load_min,r.unload_min) for r in rows})

    def test_cross_midnight_coordinates_and_executed_load(self):
        op=next(o for o in self.c['A']['operations'] if o['operation_id']=='dload')
        self.assertEqual([1430,1440,1450],numeric_handling_slots(self.c,op,1430,1450))
        op.update(start_min=470,end_min=480)
        self.n.update(release_min=400,maximum_preload_wait_min=900)
        rows=self.recipes()
        self.assertTrue(rows)
        self.assertEqual({470},{r.load_min for r in rows})

    def test_no_timer_keeps_load_immediately_before_program(self):
        self.n['timer_allowed']=False
        for r in self.recipes():
            machine=r.template['patches'][0]['rows'][0]['start_min']
            self.assertEqual(machine,r.load_min+10)

    def test_prepared_template_is_exact_and_per_recipe_mutation_isolated(self):
        r=self.recipes()[0];prepared=prepare_template(r.template)
        a=ProgramRecipe(r.template,r.load,r.unload,r.load_min,r.unload_min,prepared)
        b=ProgramRecipe(r.template,r.load,r.unload,r.load_min,r.unload_min)
        self.assertEqual(a,b);self.assertEqual(a['patches'],b['patches'])
        encoded,templates=export([[None,a]])
        self.assertEqual(a['patches'],expand(encoded[0][1],templates)['patches'])
        before=digest(r.template)
        a['needs'].append('only-this-recipe')
        self.assertNotIn('only-this-recipe',b['needs'])
        self.assertEqual(before,digest(r.template))

    def test_domain_mode_requires_explicit_valid_configuration(self):
        self.assertEqual('convenience_only',config()['handling_calendar_domain'])
        self.assertEqual('include_life_conflicts',config({'handling_calendar_domain':'include_life_conflicts'})['handling_calendar_domain'])
        with self.assertRaises(ValueError):config({'handling_calendar_domain':'widen_permissions'})


if __name__=='__main__':unittest.main()
