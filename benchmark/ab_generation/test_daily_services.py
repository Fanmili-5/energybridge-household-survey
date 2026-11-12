
from unittest import TestCase
import copy
from .daily_services import compile_daily_contract,audit_programme_cardinality

class DailyServiceTests(TestCase):
    def case(self):
        return {'household':{'controlled_function_ids':['AC','WM','DR','EV'],
          'routine':{'laundry_cycles_per_week':3},
          'service_asset_registry':{
            'AC':{'functions':['AC']},'WM':{'functions':['WM']},'DR':{'functions':['DR']},
            'DW':{'functions':['DW']},'EV':{'functions':['EV']}}}}
    def test_present_devices_have_daily_service_including_fixed(self):
        c=self.case();before=copy.deepcopy(c);d=compile_daily_contract(c,'2007-07-18')
        self.assertEqual(c,before)
        self.assertEqual({r['function']:r['required_complete_programmes'] for r in d['programme_requirements']},{'WM':1,'DR':1,'DW':1})
        self.assertEqual(next(r for r in d['programme_requirements'] if r['function']=='DW')['mode'],'fixed_routine')
    def test_legacy_weekly_frequency_does_not_remove_daily_task(self):
        d=compile_daily_contract(self.case(),'2007-07-18')
        self.assertFalse(d['legacy_weekly_experimental_frequency_overrides_daily_tasks'])
        self.assertTrue(d['A_B_same_daily_service_requirements'])
    def test_missing_dryer_is_a_failure_not_permission_to_delete(self):
        d=compile_daily_contract(self.case(),'2007-07-18')
        p={'tasks':[{'asset_id':'WM','kind':'washer','need_id':'w'},{'asset_id':'DW','kind':'dishwasher','need_id':'d'}]}
        a=audit_programme_cardinality(d,p,{'w':'2007-07-18','d':'2007-07-18'})
        self.assertFalse(a['passed']);self.assertEqual(a['errors'][0]['kind'],'dryer')
    def test_cross_midnight_stays_one_service_on_original_day(self):
        d=compile_daily_contract(self.case(),'2007-07-18')
        p={'tasks':[{'asset_id':a,'kind':k,'need_id':a,'start_min':1380,'end_min':1620}
                    for a,k in [('WM','washer'),('DR','dryer'),('DW','dishwasher')]]}
        self.assertTrue(audit_programme_cardinality(d,p,{a:'2007-07-18' for a in ('WM','DR','DW')})['passed'])
        self.assertFalse(audit_programme_cardinality(compile_daily_contract(self.case(),'2007-07-19'),p,{a:'2007-07-18' for a in ('WM','DR','DW')})['passed'])
    def test_absent_appliance_is_not_invented(self):
        c=self.case();del c['household']['service_asset_registry']['DW']
        self.assertNotIn('DW',{r['function'] for r in compile_daily_contract(c,'2007-07-18')['programme_requirements']})

class DailyContextGateTests(TestCase):
    case=DailyServiceTests.case
    def test_missing_date_binding_cannot_claim_daily_acceptance(self):
        from .daily_services import audit_context_daily_services
        c={'date':'2007-07-18','A':{'tasks':[]}}
        r=audit_context_daily_services(self.case(),c)
        self.assertFalse(r['passed']);self.assertEqual(r['errors'][0]['code'],'DAILY_SERVICE_DATE_BINDING_MISSING')
    def test_complete_daily_task_binding_passes_declared_services_gate_only(self):
        from .daily_services import audit_context_daily_services
        case=self.case();del case['household']['service_asset_registry']['EV']
        c={'date':'2007-07-18','A':{'tasks':[{'asset_id':a,'kind':k,'need_id':a}
            for a,k in [('WM','washer'),('DR','dryer'),('DW','dishwasher')]],
            'controls':[{'asset_id':'AC','kind':'ac_setpoint','start_min':0,'end_min':1440}]},
            'programme_service_date_by_need':{a:'2007-07-18' for a in ('WM','DR','DW')}}
        r=audit_context_daily_services(case,c)
        self.assertTrue(r['passed']);self.assertFalse(r['native_or_physical_execution_proven'])

class DailyDeclaredControlTests(TestCase):
    def context(self):
        case={'household':{'controlled_function_ids':['AC','WH','EV'],
            'service_asset_registry':{a:{'functions':[a]} for a in ('AC','WH','EV')}}}
        return {'date':'2007-07-18','daily_service_requirements':compile_daily_contract(case,'2007-07-18'),
                'programme_service_date_by_need':{},'A':{'tasks':[],'controls':[
                    {'asset_id':a,'kind':k,'need_id':'n','start_min':600,'end_min':900}
                    for a,k in [('AC','ac_setpoint'),('WH','tank_setpoint'),('EV','ev_charge_window')]]},
                'devices':[{'asset_id':'EV','parameters':{'target_soc':.8,'capacity_kwh':60,'initial_energy_kwh':30,'efficiency':.9}}],
                'physical_ev_connections':[{'need_id':'n','start_min':600,'end_min':1920}],
                'reference':{'ev_charging_steps':[{'need_id':'n','grid_kWh':20}]}}
    def test_all_daily_declared_services_present(self):
        from .daily_services import audit_daily_plan
        c=self.context();self.assertTrue(audit_daily_plan(c,c['A'])['passed'])
    def test_missing_thermal_control_is_rejected(self):
        from .daily_services import audit_daily_plan
        c=self.context();c['A']['controls']=[r for r in c['A']['controls'] if r['asset_id']!='WH']
        self.assertFalse(audit_daily_plan(c,c['A'])['passed'])
    def test_missing_daily_charge_cannot_pass_as_no_task_day(self):
        from .daily_services import audit_daily_plan
        c=self.context();c['A']['controls']=[r for r in c['A']['controls'] if r['asset_id']!='EV']
        self.assertFalse(audit_daily_plan(c,c['A'])['passed'])
    def test_zero_charge_is_allowed_when_initial_energy_already_meets_target(self):
        from .daily_services import audit_daily_plan
        c=self.context();c['devices'][0]['parameters']['initial_energy_kwh']=48
        c['A']['controls']=[r for r in c['A']['controls'] if r['asset_id']!='EV']
        c['reference']['ev_charging_steps']=[]
        self.assertTrue(audit_daily_plan(c,c['A'])['passed'])
