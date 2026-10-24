import unittest
from .input_evidence_audit import explain


class InputEvidenceTests(unittest.TestCase):
    def test_future_need_is_located_without_inventing_a_program(self):
        c=dict(devices=[dict(asset_id='dw')],needs=[dict(need_id='tomorrow',asset_id='dw',release_min=2000,deadline_min=3000)],
               A={'tasks':[]},horizon_min=[480,1920])
        e=dict(family='dishwasher',asset_id='dw',need_id='tomorrow',reason='service_or_excerpt_has_no_program_evidence')
        self.assertEqual(explain(c,e,dict(end_min=1140))['detail'],'release_after_excerpt')
        c['A']['tasks']=[dict(asset_id='dw',need_id='tomorrow')]
        with self.assertRaisesRegex(ValueError,'CONTRADICTS_INPUT'):explain(c,e,dict(end_min=1140))

    def test_absent_event_control_does_not_invent_off_or_room_use(self):
        c=dict(devices=[dict(asset_id='ac',room_id='bed')],A={'controls':[dict(asset_id='ac',kind='ac_setpoint',start_min=900,end_min=1080)]},occupancy={})
        e=dict(family='ac',asset_id='ac',need_id=None,reason='event_control_evidence_missing');event=dict(start_min=1080,end_min=1140)
        d=explain(c,e,event)
        self.assertEqual(d['detail'],'controls_outside_event');self.assertIsNone(d['event_room_use_declared'])
        c['occupancy']['bed']=[]
        self.assertIs(explain(c,e,event)['event_room_use_declared'],False)
        c['A']['controls'][0]['end_min']=1090
        with self.assertRaisesRegex(ValueError,'CONTRADICTS_INPUT'):explain(c,e,event)


if __name__=='__main__':unittest.main()
