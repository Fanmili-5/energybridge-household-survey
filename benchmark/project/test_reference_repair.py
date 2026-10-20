import csv,io,tempfile,unittest
from pathlib import Path
from .reference_solver_repair import review,roots,ENGINE_FILES
from .reference_physics_weather import validate_replacement
from .reference_replenishment import candidate_dates,first_computable
from .reference_entry_door import finite_entry

class RepairTests(unittest.TestCase):
    def test_entry_door_preserves_resistance_and_internal_door_representation(self):
        text='Material:NoMass,ReferenceDoorR,Smooth,.2,.9,.7,.7;Construction,ReferenceDoor,ReferenceDoorR;BuildingSurface:Detailed,exwall,Wall,wall,zone,,Outdoors;BuildingSurface:Detailed,inwall,Wall,wall,zone,,Surface;FenestrationSurface:Detailed,entry,Door,ReferenceDoor,exwall;FenestrationSurface:Detailed,inside,Door,ReferenceDoor,inwall;'
        changed,p=finite_entry(text)
        from benchmark.housing_simulation.kernel.core_tools import parse_idf
        rows=parse_idf(changed);doors={r[1]:r for r in rows if r[0]=='FenestrationSurface:Detailed'}
        self.assertEqual(doors['inside'][3],'ReferenceDoor');self.assertNotEqual(doors['entry'][3],'ReferenceDoor')
        material=next(r for r in rows if r[0]=='Material')
        self.assertAlmostEqual(float(material[3])/float(material[4]),.2);self.assertEqual(p['surface_names'],['entry'])
    def test_first_computable_never_skips_pending_or_filters_bad_household_outcomes(self):
        good={'both_native_arms_complete':True,'native_numerical_pass':True,'weather_pass':True,'paired_integrity_pass':True,
              'VPP_target_met':False,'service_execution_pass':False,'energy_increased':True}
        bad={**good,'native_numerical_pass':False}
        self.assertIsNone(first_computable(['a','b'],{'b':good}))
        self.assertEqual(first_computable(['a','b'],{'a':bad,'b':good}),'b')
        self.assertEqual(first_computable(['a','b'],{'a':good,'b':good}),'a')
    def test_unique_root_reproduced_and_false_branch_refused(self):
        self.assertEqual(len(roots(9.75,.001115565188229084,75880)),1)
        self.assertEqual(len(roots(2.2333316802978516,.0028350967913866043,102300)),2)
        log='EBTWB_REPAIR_APPLIED\ttdb=9.75\tw=0.001115565188229084\tp=75880\told=0.006825701742380781\told_residual=1.0262941549402929e-05\tnew=-0.60292205912992358\tnew_residual=1.9651470554993278e-11'
        self.assertTrue(review(log,ENGINE_FILES)['passed'])
        with self.assertRaises(ValueError):review(log.replace('new=-0.60292205912992358','new=0.0'),ENGINE_FILES)

    def test_unresolved_is_not_admitted_and_unknown_build_is_not_trusted(self):
        proof=review('EBTWB_REPAIR_UNRESOLVED\tstatus=multiple_roots\troots=2',ENGINE_FILES)
        self.assertFalse(proof['passed']);self.assertEqual(proof['failures'],['bounded_wetbulb_multiple_roots'])
        with self.assertRaisesRegex(ValueError,'UNRECOGNIZED'):review('',{})

    def test_replenishment_date_order_is_stable_excludes_existing_dates_and_changes_by_slot(self):
        a=candidate_dates('h','slot1',{'2025-01-01'},42)
        self.assertEqual(a,candidate_dates('h','slot1',{'2025-01-01'},42))
        self.assertEqual(len(a),364);self.assertNotIn('2025-01-01',a)
        self.assertNotEqual(a,candidate_dates('h','slot2',{'2025-01-01'},42))

    def test_weather_same_station_is_required_and_invalid_dewpoint_is_rejected(self):
        import datetime as dt
        def epw(station='123456',bad=False):
            output=io.StringIO();w=csv.writer(output);w.writerow(['LOCATION','X','Y','CHN','TEST',station,39,118,8,10])
            for _ in range(7):w.writerow(['header'])
            for i in range(365):
                d=dt.date(2025,1,1)+dt.timedelta(days=i)
                for h in range(1,25):w.writerow([2005,d.month,d.day,h,0,'?',20,25 if bad and i==0 and h==1 else 10,50,101325])
            return output.getvalue()
        with tempfile.TemporaryDirectory()as folder:
            a=Path(folder)/'a.epw';b=Path(folder)/'b.epw';a.write_text(epw());b.write_text(epw())
            self.assertTrue(validate_replacement(a,b)['passed'])
            b.write_text(epw('123457'))
            with self.assertRaisesRegex(ValueError,'STATION'):validate_replacement(a,b)
            b.write_text(epw(bad=True))
            with self.assertRaisesRegex(ValueError,'DOMAIN'):validate_replacement(a,b)

if __name__=='__main__':unittest.main()
