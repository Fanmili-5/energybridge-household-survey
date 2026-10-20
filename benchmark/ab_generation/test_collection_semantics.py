"""Regressions for the real 40->27 error and irrelevant joint components."""
import copy
import unittest
from .test_collection import fixture
from .collection import review
from .collection_candidates import _raw_thermal, _raw_programs, _finish, _request, generate_day
from .collection_design import design
from .collection_thermal import state
from .collection_relevance import direct, explain
from .generate import binding
from .model import apply
from .validation.collection_v3.independent_semantics import literal_errors


class CommandSemanticsTests(unittest.TestCase):
    def test_cross_event_patch_with_only_pre_event_change_is_not_an_event_root(self):
        c=fixture();c['A']['controls']=[r for r in c['A']['controls'] if r['kind']!='ac_setpoint']+[
            {'asset_id':'ac','kind':'ac_setpoint','start_min':480,'end_min':1080,
             'heating_setpoint_C':20.,'cooling_setpoint_C':40.,'fan_operating_mode':0},
            {'asset_id':'ac','kind':'ac_setpoint','start_min':1080,'end_min':1440,
             'heating_setpoint_C':20.,'cooling_setpoint_C':26.,'fan_operating_mode':0}]
        component={'family':'ac','asset_id':'ac','magnitude':{'axis':'cooling'},'patches':[
            {'type':'control_interval','asset_id':'ac','kind':'ac_setpoint','start_min':1050,'end_min':1110,
             'values':{'cooling_setpoint_C':26.}}]}
        self.assertEqual(direct(c,component,design()['event']),[])

    def test_fallback_is_not_a_room_temperature_or_native_off(self):
        c=fixture();a=next(r for r in c['A']['controls'] if r['kind']=='ac_setpoint')
        a={**a,'cooling_setpoint_C':40.}
        decoded=state(a,c['reference']['ac_control_contract'])
        self.assertEqual(decoded['mode'],'cooling_stop_fallback')
        self.assertIsNone(decoded['cooling_setpoint_C'])
        self.assertIsNone(decoded['compressor_running'])
        self.assertEqual(state(a,None)['mode'],'thermostat_control')

    def test_actual_40_to_27_case_has_state_and_time_axes(self):
        c=fixture();c['A']['controls']=[r for r in c['A']['controls'] if r['kind']!='ac_setpoint']+[
            {'asset_id':'ac','kind':'ac_setpoint','start_min':480,'end_min':1080,
             'heating_setpoint_C':5.,'cooling_setpoint_C':40.,'fan_operating_mode':0},
            {'asset_id':'ac','kind':'ac_setpoint','start_min':1080,'end_min':1440,
             'heating_setpoint_C':20.,'cooling_setpoint_C':26.,'fan_operating_mode':0}]
        c['reference']['binding']=binding(c);before=copy.deepcopy(c);cfg=design()
        device=next(d for d in c['devices'] if d['asset_id']=='ac')
        raw=next(r for r in _raw_thermal(c,device,cfg) if r['mechanism']=='precondition_and_relax'
            and r['magnitude']['service_delta_C']==1 and r['magnitude']['direction']=='opposing'
            and r['magnitude']['precondition_min']==30 and r['magnitude']['duration_min']==60)
        child=_finish(c,raw,cfg);child['relative_level']='low';ac=child['magnitude']['ac_intervention']
        self.assertEqual(child['absolute_level'],'state_change')
        self.assertEqual(child['magnitude']['actual_max_command_delta_C'],13)
        self.assertEqual(ac['additional_thermostat_enabled_min'],30)
        self.assertIsNone(ac['phases'][0]['same_time_setpoint_delta_C'])
        self.assertEqual(ac['phases'][0]['B']['cooling_setpoint_C'],27)
        self.assertEqual(ac['amplitude_axes']['temperature_offset'],'medium')
        row=_request(c,[child],cfg)
        self.assertTrue(review(c,row)[0]['passed'])
        self.assertEqual(literal_errors(c,row,cfg),[])
        self.assertFalse(any('intensity=' in t for t in row['tags']))
        bad=copy.deepcopy(row);bad['components'][0]['magnitude']['ac_intervention']['additional_thermostat_enabled_min']=0
        self.assertIn('AC_COMMAND_SEMANTICS_OR_AMPLITUDE_MISMATCH',review(c,bad)[0]['failed_checks'])
        self.assertIn('AC_DOSE_AXIS_MISMATCH',literal_errors(c,bad,cfg))
        bad=copy.deepcopy(row);bad['components'][0]['magnitude']['ac_intervention']['phases'][0]['same_time_setpoint_delta_C']=-13
        self.assertIn('FALLBACK_COUNTED_AS_TEMPERATURE_DOSE',literal_errors(c,bad,cfg))
        self.assertEqual(c,before)

    def test_stop_cooling_duration_has_no_fictitious_delta_temperature(self):
        c=fixture();cfg=design();device=next(d for d in c['devices'] if d['asset_id']=='ac')
        requests=[r for r in _raw_thermal(c,device,cfg) if r['mechanism']=='event_cooling_stop_fallback']
        self.assertEqual({r['magnitude']['duration_min'] for r in requests},{20,40,60})
        for raw in requests:
            child=_finish(c,raw,cfg);child['relative_level']='low'
            self.assertIsNone(child['magnitude']['service_delta_C'])
            ac=child['magnitude']['ac_intervention']
            self.assertEqual(ac['cooling_stop_requested_min'],raw['magnitude']['duration_min'])
            self.assertIsNone(ac['max_comparable_setpoint_delta_C'])
            row=_request(c,[child],cfg);check,b=review(c,row)
            self.assertTrue(check['passed'],check)
            self.assertEqual(literal_errors(c,row,cfg),[])
            self.assertEqual(next(r['cooling_setpoint_C'] for r in b['controls'] if r['asset_id']=='ac' and r['start_min']<=1150<r['end_min']),26)

    def test_zero_net_event_rescheduling_stays_eligible(self):
        c=fixture();c['A']['tasks']=[r for r in c['A']['tasks'] if r['need_id']!='wash:dry']
        next(r for r in c['A']['tasks'] if r['need_id']=='wash').update(start_min=1080,end_min=1100)
        for r in c['A']['operations']:
            if r['need_id']=='wash':
                r.update(start_min=1060 if r['kind']=='load' else 1120,end_min=1070 if r['kind']=='load' else 1130)
        c['reference']['binding']=binding(c);cfg=design();device=next(d for d in c['devices'] if d['asset_id']=='washer')
        raw=next(r for r in _raw_programs(c,device,cfg) if r['mechanism']=='timer_only' and r['magnitude']['signed_machine_shift_min']==10)
        child=_finish(c,raw,cfg);child['relative_level']='low';row=_request(c,[child],cfg)
        self.assertEqual(row['features']['event'],'zero')
        self.assertEqual(row['known_event_reduction_kWh'],0)
        self.assertTrue(row['event_relevance']['passed'])
        self.assertTrue(review(c,row)[0]['passed'])
        self.assertEqual(literal_errors(c,row,cfg),[])

    def test_external_support_needs_a_specific_new_resource_conflict(self):
        c=fixture()
        root={'id':'root','family':'dishwasher','patches':[
            {'type':'rows','collection':'tasks','identity':'task_id','rows':[
                {**next(t for t in c['A']['tasks'] if t['task_id']=='dishes'),'start_min':1090,'end_min':1180}]},
            {'type':'rows','collection':'operations','identity':'operation_id','rows':[
                {**next(o for o in c['A']['operations'] if o['operation_id']=='dload'),'start_min':1020,'end_min':1030}]}]}
        support={'id':'support','family':'washer','patches':[
            {'type':'rows','collection':'operations','identity':'operation_id','rows':[
                {**next(o for o in c['A']['operations'] if o['operation_id']=='unload'),'start_min':1040,'end_min':1050}]}]}
        event=design()['event'];report=explain(c,[root,support],event)
        self.assertTrue(report['passed'])
        self.assertEqual(report['components']['support']['role'],'support_event_request')
        self.assertTrue(report['components']['support']['evidence'][0]['absent_in_A'])
        self.assertFalse(explain(c,[support],event)['passed'])
        bad=copy.deepcopy(root);bad['patches'][1]['rows'][0].update(start_min=1000,end_min=1010)
        self.assertFalse(explain(c,[bad,support],event)['passed'])

    def test_no_opportunity_does_not_license_outside_event_padding(self):
        c=fixture()
        for aid in c['authority']['assets']:
            c['authority']['assets'][aid]['target_control_authorized']=aid=='dishes'
        n=next(n for n in c['needs'] if n['asset_id']=='dishes');n['release_min']=1200
        for r in c['A']['tasks']:
            if r['asset_id']=='dishes':r.update(start_min=1230,end_min=1320)
        for r in c['A']['operations']:
            if r['asset_id']=='dishes':r.update(start_min=1210 if r['kind']=='load' else 1330,end_min=1220 if r['kind']=='load' else 1340)
        c['reference']['binding']=binding(c);result=generate_day(c,design())
        self.assertEqual([r['features']['device_count'] for r in result['rows']],['0'])
        self.assertTrue(result['relevance_diagnostics'])
        self.assertTrue(result['no_retries_or_replacements'])


if __name__=='__main__':unittest.main()
