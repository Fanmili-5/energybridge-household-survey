import copy
import tempfile
import unittest
from pathlib import Path
from benchmark.ab_generation.common import read,save
from .evidence_report import cohort_summary,selection_summary,run


class EvidenceReportTests(unittest.TestCase):
    def test_missing_evidence_cannot_be_rendered_as_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=root/'inputs.json'
            save(manifest,dict(schema='eb.research_evidence_inputs.v1',revision='test',cohorts={
                'fifty':dict(expected_slots=500,acceptance='missing.json',selected_audit='missing-selected.json')}))
            result=run(manifest,root/'out');report=read(root/'out/EVIDENCE_REPORT.json')
            self.assertEqual(result['missing'],2)
            self.assertFalse(report['all_manifest_inputs_available'])
            self.assertFalse(report['automatic_goal_completion'])
            self.assertTrue(read(root/'out/RETAINED_REFERENCES.json')['sha_verified'])
            self.assertEqual((root/'out/INPUT_MANIFEST.original.json').read_bytes(),manifest.read_bytes())
            self.assertNotIn('fifty',report['cohorts'])
            self.assertIn('缺少完整证据',(root/'out/EVIDENCE_REPORT.md').read_text())
            with self.assertRaises(FileExistsError):run(manifest,root/'out')

    def test_unknown_and_overlap_not_converted_to_physical_failure(self):
        row=dict(life_issues=['late'],soft_tension=True,member_disagreement=True,
            nominal_event_delta_kWh=0,thermal_unknown=True,human_fields_empty=True,actual_outcome_empty=True)
        report=dict(opportunities=dict(potential=2,witnessed=1,selected=1,gaps={'search_budget':1},
            input_mechanism_evidence_unknown=3,family_exposure={},selected_joint_order={'1':1},semantic_repeat_excess=0),
            numeric_exploration=dict(by_strength={},all_candidate_cases=4,all_candidate_components=6),
            complete_date_accounting=True,expected_date_slots=1,engineering_check_pass=True,
            independent_all_candidate_causal_pass=True,source_check={'passed':True},semantic_coverage={})
        result=cohort_summary(report,[row],1)
        self.assertTrue(result['engineering_checks_passed'])
        self.assertFalse(result['known_potential_mechanisms_closed'])
        self.assertEqual(result['input_evidence_unknown'],3)
        self.assertEqual(result['long_tails']['nominal_zero'],1)
        self.assertEqual(result['long_tails']['thermal_unknown'],1)
        self.assertFalse(result['long_tails']['actual_no_response_or_physical_failure_observed'])
        self.assertFalse(cohort_summary(report,[row],500)['engineering_checks_passed'])
        self.assertFalse(cohort_summary(report,[row],1,[])['engineering_checks_passed'])
        changed=copy.deepcopy(row);changed['human_fields_empty']=False
        self.assertFalse(cohort_summary(report,[changed],1)['engineering_checks_passed'])

    def test_duplicate_selection_arms_do_not_pass_accounting(self):
        row=dict(arm='uniform_0',date_accounting_pass=True,answer_and_actual_fields_empty=True)
        result=selection_summary([row,row],{})
        self.assertFalse(result['all_dates_accounted'])
        self.assertEqual(result['duplicate_arm_names'],['uniform_0'])

    def test_later_reconciliation_does_not_erase_original_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            save(root/'domain.json',dict(all_passed=False,slots=500,old_literal_commands=20,
                new_literal_commands=30,removed_old_literal_commands=0))
            save(root/'bridge.json',dict(passed=True,raw_key_equality_failures=450,
                prior_corrected_declarations_identical_on_all500=True))
            save(root/'inputs.json',dict(schema='eb.research_evidence_inputs.v1',revision='test',cohorts={},
                additional_evidence=dict(fifty_domain_expansion='domain.json',
                    fifty_domain_ledger_reconciliation='bridge.json')))
            run(root/'inputs.json',root/'out')
            text=(root/'out/EVIDENCE_REPORT.md').read_text()
            self.assertIn('all_passed=False',text)
            self.assertIn('对应说明 passed=True',text)
            self.assertFalse(read(root/'out/EVIDENCE_REPORT.json')['automatic_goal_completion'])


if __name__=='__main__':unittest.main()
