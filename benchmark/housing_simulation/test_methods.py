"""Independent witnesses and negative controls for the reference-method upgrade."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from .pipeline import HERE,read
from .installation import place,InstallationInfeasible,InstallationUnresolved,_solve
from .loads import metabolic_watts,cooking_minutes
from .geometry_reference import check_geometry_reference
from .robustness import morris_design,convergence,airflow_balance


class ReferenceMethodTests(unittest.TestCase):
    def test_activity_heat_uses_activity_and_explicit_body_scale(self):
        self.assertEqual(metabolic_watts('sleep'),72)
        self.assertEqual(metabolic_watts('home_idle'),108)
        self.assertEqual(metabolic_watts('cooking'),171)
        self.assertEqual(metabolic_watts('bath'),126)
        self.assertEqual(metabolic_watts('handling',.75),135)

    def test_cooking_is_union_of_explicit_home_cooking_only(self):
        day={'calendars':{'a':[{'activity':'dinner','start_min':1140,'end_min':1170,'location':'home'},
                               {'activity':'cooking','start_min':1100,'end_min':1120,'location':'home'}]},
             'shared':{'member_calendars':{'b':[{'activity':'cooking','start_min':1110,'end_min':1130,'location':'home'}]}}}
        self.assertEqual(cooking_minutes(day),{1100,1110,1120})

    def test_joint_packing_recovers_rotation_counterexample(self):
        # First-fit puts a horizontally at the bottom; b then cannot fit either
        # orientation. Jointly rotating a gives a feasible witness along b.
        items=[{'object_id':'a','footprint_m':[2,1]},{'object_id':'b','footprint_m':[1.9,3.2]}]
        result=place(items,{'room_id':'r','usable_rect_m':[0,0,3.1,4.1]})
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['rotation_degrees'],90)
        a,b=[x['clearance_rect_m']for x in result]
        self.assertTrue(a[2]+.1<=b[0]+1e-7 or b[2]+.1<=a[0]+1e-7)

    def test_clearance_can_make_body_only_fit_infeasible(self):
        room={'room_id':'r','usable_rect_m':[0,0,2.1,2.9]}
        self.assertEqual(len(place([{'object_id':'a','footprint_m':[2,2]}],room)),1)
        with self.assertRaises(InstallationInfeasible):place([{'object_id':'a','footprint_m':[2,2],'clearance_m':[.2,.2,.2,.2]}],room)

    def test_solver_limit_is_unresolved_never_space_infeasible(self):
        _solve.cache_clear()
        with patch('benchmark.housing_simulation.installation.milp',return_value=SimpleNamespace(status=1)):
            with self.assertRaises(InstallationUnresolved):place([{'object_id':'limited','footprint_m':[.987,1.234]}],{'room_id':'r','usable_rect_m':[0,0,4.01,4.02]})
        _solve.cache_clear()

    def test_source_geometry_requires_whole_dwelling_scope(self):
        declaration={'geometry_reference':{'profile_id':'xia2025_P3','source_area_to_model_gross_factor':1.18,'mapping_rationale':'Explicit reference conversion;not an observed survey ratio.'}}
        layout={'whole_unit_building_area_m2':90,'rooms':[{'room_id':x,'census_room_class':'bedroom','usable_area_m2':15}for x in ('a','b')]}
        self.assertTrue(check_geometry_reference(declaration,layout)['checks']['whole_dwelling_bedroom_count'])
        bad=copy.deepcopy(layout);bad['rooms'].append({'room_id':'neighbor','census_room_class':'bedroom','usable_area_m2':10})
        with self.assertRaisesRegex(ValueError,'whole dwelling bedroom'):check_geometry_reference(declaration,bad)
        bad=copy.deepcopy(layout);bad['whole_unit_building_area_m2']=1000
        with self.assertRaisesRegex(ValueError,'area domain'):check_geometry_reference(declaration,bad)
        declaration['geometry_reference'].pop('mapping_rationale')
        with self.assertRaisesRegex(ValueError,'explicit area mapping'):check_geometry_reference(declaration,layout)

    def test_morris_has_one_parameter_per_edge_and_reproducible_grid(self):
        p=read(HERE/'STUDY_PLAN.json');states,edges=morris_design(p)
        self.assertEqual((states,edges),morris_design(p));self.assertEqual(len(states),12);self.assertEqual(len(edges),10)
        points={x['id']:x for x in states}
        for e in edges:
            a,b=points[e['from']]['normalized'],points[e['to']]['normalized']
            changed=[n for n in a if abs(a[n]-b[n])>1e-10]
            self.assertEqual(changed,[e['parameter']]);self.assertAlmostEqual(b[changed[0]]-a[changed[0]],e['normalized_delta'])
            self.assertTrue(all(-1e-12<=v<=1+1e-12 for v in b.values()))

    def test_convergence_rejects_effect_drift_despite_small_total_change(self):
        a={'case':{'A_kWh':100,'B_kWh':99,'B_minus_A_kWh':-1,'states':{'Zone Mean Air Temperature|R|A':[25]*2}}}
        b=copy.deepcopy(a);b['case'].update(B_kWh=99.5,B_minus_A_kWh=-.5)
        result=convergence(a,b)
        self.assertFalse(result['passed']);self.assertTrue(result['cases']['case']['checks']['B_energy'])
        self.assertTrue(convergence(a,a)['passed'])

    def test_mass_balance_fails_a_missing_or_unbalanced_link(self):
        env={'links':[{'surface':'EXT','from':'room','to':None}]}
        trace={'AFN Linkage Node 1 to Node 2 Mass Flow Rate|EXT':{'unit':'kg/s','values':[[0,.1]]},
               'AFN Linkage Node 2 to Node 1 Mass Flow Rate|EXT':{'unit':'kg/s','values':[[0,.1]]}}
        self.assertTrue(airflow_balance(trace,env,['room'])['passed'])
        trace['AFN Linkage Node 2 to Node 1 Mass Flow Rate|EXT']['values'][0][1]=0
        self.assertFalse(airflow_balance(trace,env,['room'])['passed'])
        trace.pop('AFN Linkage Node 2 to Node 1 Mass Flow Rate|EXT')
        with self.assertRaisesRegex(ValueError,'missing AFN flow'):airflow_balance(trace,env,['room'])


if __name__=='__main__':unittest.main()
