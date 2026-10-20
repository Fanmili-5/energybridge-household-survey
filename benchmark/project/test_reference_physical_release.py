"""Distinguish adverse household outcomes from corrupt/unbound physics."""
import unittest
import hashlib
import tempfile
from pathlib import Path
from .reference_physics_results import integrity_failures,mixed_water_delivery,native_numerical_failures
from .reference_weather_audit import native_weather_review
from .reference_physical_release import require_computed_consequences


class PhysicalInformationTests(unittest.TestCase):
    def complete_outcomes(self):
        return {'metered_energy':{'primary_24h':{'A':2.,'B':3.,'B_minus_A':1.}},
                'simulated_facility_cost':{'currency':'CNY','intervals':{'primary_24h':{'status':'complete','A':1.,'B':2.,'B_minus_A':1.}}},
                'events':[{'target_met':False,'A_kWh':2.,'B_kWh':3.,'aligned_response_kw':-1.}],
                'temperature_outcomes':[{'A':{'minimum_C':20.,'mean_C':21.,'maximum_C':22.},'B':{'minimum_C':25.,'mean_C':26.,'maximum_C':27.}}]}

    def test_formal_collection_rejects_unknown_even_when_all_native_runs_finished(self):
        rows=[{'case_id':str(i),'status':'computed','actual_outcomes':self.complete_outcomes()} for i in range(500)]
        require_computed_consequences(rows)
        rows[2].update(status='audit_failed',actual_outcomes=None)
        with self.assertRaisesRegex(ValueError,'FORMAL_COLLECTION_REQUIRES_COMPUTED_CONSEQUENCES:1'):
            require_computed_consequences(rows)

    def test_readiness_does_not_filter_adverse_service_or_target_failures(self):
        rows=[{'case_id':str(i),'status':'computed','audit_status':'failed','failed_checks':['B_EV_departure_target'],
               'actual_outcomes':self.complete_outcomes()}for i in range(500)]
        require_computed_consequences(rows)

    def test_computed_marker_alone_does_not_bypass_readiness(self):
        rows=[{'case_id':str(i),'status':'computed','actual_outcomes':{}}for i in range(500)]
        with self.assertRaisesRegex(ValueError,'FORMAL_CORE_CONSEQUENCES_INCOMPLETE'):
            require_computed_consequences(rows)

    def test_weather_check_covers_cross_year_history_and_recovery_not_unrelated_months(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'weather.epw'
            p.write_text('\n'*8+'2005,12,31,24,0,?,0,0,113\n2005,1,9,1,0,?,0,0,255\n2005,7,1,1,0,?,0,0,130\n')
            h=hashlib.sha256(p.read_bytes()).hexdigest()
            review=native_weather_review(p,h,'RunPeriod,case,12,15,2025,1,9,2026;')
            self.assertFalse(review['passed'])
            self.assertEqual([r['RH_percent']for r in review['invalid_RH_records']],[113,255])
            self.assertEqual(review['weather_sha256'],h)
            self.assertFalse(review['source_modified'])

    def test_weather_native_tolerance_missing_sentinel_and_outside_period_are_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'weather.epw'
            p.write_text('\n'*8+'2005,1,1,1,0,?,0,0,110\n2005,1,2,1,0,?,0,0,999\n2005,7,1,1,0,?,0,0,113\n')
            h=hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertTrue(native_weather_review(p,h,'RunPeriod,case,1,1,2025,1,9,2025;')['passed'])
            with self.assertRaisesRegex(ValueError,'WEATHER_INPUT_HASH_MISMATCH'):
                native_weather_review(p,'0'*64,'RunPeriod,case,1,1,2025,1,9,2025;')

    def test_successful_process_with_internal_nonconvergence_is_not_reliable_consequences(self):
        text='** Warning ** WetBulb not converged after 101 iterations(PsyTwbFnTdbWPb)'
        self.assertEqual(native_numerical_failures(text),['wetbulb_iteration_not_converged'])
        self.assertEqual(native_numerical_failures('** Severe  ** invalid native state'),['native_severe_error'])

    def test_intermediate_iteration_range_warning_does_not_invent_failure(self):
        text='** Warning ** Temperature out of range [-100. to 200.] (PsyPsatFnTemp)\nRoutine=PsyTwbFnTdbWPb'
        self.assertEqual(native_numerical_failures(text),[])

    def test_adverse_service_is_not_an_engineering_rejection_filter(self):
        check={'checks':{'B_service_execution':False,'B_EV_departure_target':False,
                         'B_electrical_supply':False,'recovery_observable_residuals':False,
                         'pre_notice_trajectory_equal':True,'A_meter_closure':True}}
        self.assertEqual(integrity_failures(check),[])

    def test_unreliable_pair_remains_diagnostic_and_unknown(self):
        check={'checks':{'B_service_execution':False,'pre_notice_trajectory_equal':False,
                         'B_program_energy':False,'readback_complete':False}}
        self.assertEqual(set(integrity_failures(check)),{'pre_notice_trajectory_equal','B_program_energy','readback_complete'})

    def test_mixed_water_reports_actual_cold_delivery_without_success_label(self):
        meta={'tank_name':'TANK','hot_water_model':'native_mixed_water_plant','water_needs':[{'release_min':480,'deadline_min':500,'quantity':30,'target_C':40}]}
        trace={'Water Use Equipment Total Volume|SHOWER':{'unit':'m3','native_aggregation':'Sum','values':[[480,.01],[490,.02]]},
               'Water Use Equipment Mixed Water Temperature|SHOWER':{'unit':'C','values':[[480,20],[490,35]]}}
        row=mixed_water_delivery(meta,trace,480,500)
        self.assertEqual(row['delivered_mixed_liters'],30);self.assertEqual(row['requested_mixed_liters'],30)
        self.assertAlmostEqual(row['volume_weighted_reported_temperature_C'],30)
        self.assertEqual(row['minimum_active_10min_mean_C'],20);self.assertFalse(row['service_pass_inferred'])
        del trace['Water Use Equipment Total Volume|SHOWER']['native_aggregation']
        self.assertEqual(mixed_water_delivery(meta,trace,480,500)['status'],'unavailable')


class ParticipantPresentationTests(unittest.TestCase):
    def test_separate_laundry_display_hides_engineering_details_and_keeps_plans(self):
        import json,subprocess,copy
        from .reference_refined_release import renderer,participant_html
        from .reference_collection_release import typed_control_copy
        from .questionnaire import HERE,COLLECTOR
        with tempfile.TemporaryDirectory() as temp:
            view=Path(temp)/'view.js'
            view.write_text(renderer(typed_control_copy((HERE/'examples/questionnaire/public/view.js').read_text())))
            p={'household_id':'h','province':'测试','members_count':2,'generations':1,
               'household_area_m2':70,'relationships':[],'support':[],
               'display_housing':{'rooms':[],'target_H7':2,'shared_household_count_design':1},
               'devices':[{'asset_id':'laundry','types':['washer','dryer'],'room_id':'washroom'}]}
            washer={'asset_id':'laundry','kind':'washer','need_id':'n','start_min':1100,'end_min':1220}
            dryer={'asset_id':'laundry','kind':'dryer','need_id':'n:dry','upstream_need_id':'n','start_min':1220,'end_min':1310}
            load={'asset_id':'laundry','kind':'load','need_id':'n','start_min':1090,'end_min':1100}
            changes=[{'asset_id':'laundry','kind':r['kind'],'group':'tasks' if r is not load else 'operations',
                      'A':r,'B':{**r,'start_min':r['start_min']+60,'end_min':r['end_min']+60}}
                     for r in (washer,dryer,load)]
            c={'household_id':'h','date':'2025-01-01','window_min':[480,1920],
               'project_presentation':{'family_lines':['成员资料','家庭关系','你代入成员1']},
               'context':{'needs':{'A':[{'asset_id':'laundry','kind':'washer','need_id':'n','release_min':480,'deadline_min':1920}]}},
               'changes':changes,'plans':{},'outcome_status':'not_computed','impact':None,'VPP_results':None,
               'VPP_requests':[{'start_min':1080,'end_min':1140,'notification_min':480,'target_kw':1,'direction':'down'}]}
            original=copy.deepcopy(c)
            run="""require(process.argv[1]);const c=JSON.parse(process.argv[2]),p=JSON.parse(process.argv[3]);
const ui=globalThis.EBSimple50,nodes=ui.presentationNodes(c,p),shown=ui.displayed(c,p);
console.log(JSON.stringify({nodes,shown,case:c}));"""
            value=json.loads(subprocess.check_output(['node','-e',run,str(view),json.dumps(c),json.dumps(p)],text=True))
            cards=value['nodes']['changes']
            self.assertEqual([r['attrs']['data-device-kind'] for r in cards],['washer','dryer'])
            self.assertEqual([r['attrs']['data-asset-id'] for r in cards],['laundry','laundry'])
            shown=value['shown'];self.assertIn('洗衣机',shown['family']);self.assertIn('烘干机',shown['family'])
            for when in ['18:20','20:20','19:20','21:20','21:50','22:50']:self.assertIn(when,shown['changes'])
            for word in ['洗烘一体机','装载','取出','查看完整资料','计划说明']:self.assertNotIn(word,shown['changes']+shown['impacts']+shown['family'])
            self.assertEqual(shown['schedule'],'');self.assertIn('未计算',shown['impacts'])
            self.assertEqual(value['case'],original)
            html=participant_html('<p id="score-note">很长的说明</p>'+ (HERE/'refined91/index.html').read_text())
            self.assertNotIn('<small>',html)
            self.assertEqual(html.count('class="score-option"'),24)
            self.assertNotIn('type="number"',html)
            self.assertNotIn(' checked',html)
            for value in range(6):self.assertEqual(html.count('value="'+str(value)+'" required'),4)
            self.assertNotIn('step="0.1"',html)
            integer_check="require(process.argv[1]);require(process.argv[2]);const a={decision:'accept',score:0,comfort_score:0,energy_score:0,vpp_score:0,reason:'test'};globalThis.EBSimple50.answer(a);for(let v=0;v<=5;v++)globalThis.EBSimple50.answer({...a,score:v});let rejected=0;for(const key of ['score','comfort_score','energy_score','vpp_score']){try{globalThis.EBSimple50.answer({...a,[key]:2.5});}catch{rejected++;}}console.log(rejected);"
            self.assertEqual(subprocess.check_output(['node','-e',integer_check,str(HERE/'refined91/required-response.js'),str(view)],text=True).strip(),'4')
            for key in ['score','comfort_score','energy_score','vpp_score','reason','decision']:
                self.assertIn('name="'+key+'"',html)


if __name__=='__main__':unittest.main()
