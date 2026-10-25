import copy
import unittest

from benchmark.ab_generation.unified.change_axes import annotate_frozen_row
from benchmark.ab_generation.unified.test_change_axes import thermal, EVENT
from .axis_acceptance import check


def proposal(component):
    c=copy.deepcopy(component)
    c.update(id='component',unit='unit',event_relevance={'role':'direct_event_request'})
    return dict(id='case',household_id='h',date='day',components=[c],patches=copy.deepcopy(c['patches']),
        component_ids=['component'],independent_units=1,issues=['life_conflict'],features={},judgment_context=[],
        consent_status='confirmation_required',known_event_reduction_kWh=0,unknown_thermal_response=True,
        human_acceptance=None,human_score=None,human_reason=None,actual_outcomes=None)


class IndependentAxisAcceptanceTests(unittest.TestCase):
    def test_literal_clock_audit_accepts_and_detects_wrong_pre_event_minutes(self):
        c,component=thermal()
        old=proposal(component);new=annotate_frozen_row(c,old,EVENT)
        self.assertEqual([],check(c,old,new))
        new['components'][0]['change_axes']['thermal']['timing']['pre_event_preparation_min']=10
        self.assertIn('THERMAL_BOUNDARY_MINUTES_MISMATCH',check(c,old,new))

    def test_original_life_conflict_cannot_be_erased(self):
        c,component=thermal();old=proposal(component);new=annotate_frozen_row(c,old,EVENT)
        new['issues']=[]
        self.assertIn('SOURCE_ACTION_OR_JUDGMENT_CHANGED',check(c,old,new))

    def test_labor_and_retiming_are_checked_against_literal_operations(self):
        c=dict(A=dict(tasks=[dict(task_id='t',start_min=110,end_min=230)],controls=[],
            operations=[dict(operation_id='load',start_min=100,end_min=110),
                        dict(operation_id='unload',start_min=230,end_min=240)]))
        component=dict(family='washer',asset_id='washer',mechanism='retimed_handling',relative_level='small_relative',
            magnitude={'signed_machine_shift_min':10},patches=[
                dict(type='rows',collection='tasks',rows=[dict(task_id='t',start_min=120,end_min=240)]),
                dict(type='rows',collection='operations',rows=[dict(operation_id='load',kind='load',start_min=100,end_min=110),
                    dict(operation_id='unload',kind='unload',start_min=440,end_min=450)])])
        old=proposal(component);new=annotate_frozen_row(c,old,EVENT)
        self.assertEqual([],check(c,old,new))
        new['components'][0]['change_axes']['handling']['active_duration_delta_min']=210
        self.assertIn('HANDLING_AXIS_OR_EXTRA_WORK_MISMATCH',check(c,old,new))


if __name__=='__main__':unittest.main()
