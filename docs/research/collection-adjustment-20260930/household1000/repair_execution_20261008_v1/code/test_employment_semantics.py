import unittest
from employment_semantics import decode_current_work


class EmploymentEvidenceTests(unittest.TestCase):
    def test_changed_job_is_still_current_work(self):
        x = decode_current_work(2)
        self.assertEqual(x["current_work_evidence"], "has_work")
        self.assertEqual(x["main_job_continuity_evidence"], "changed_main_job_since_last_year")

    def test_known_no_current_work_remains_separate_from_last_year(self):
        self.assertEqual(decode_current_work(3, last_year_work=1)["current_work_evidence"], "no_current_work")

    def test_retirement_skip_does_not_fabricate_observed_current_status(self):
        x = decode_current_work(None, last_year_work=2, no_work_reason=3)
        self.assertEqual(x["missing_kind"], "questionnaire_structural_skip_supported")
        self.assertEqual(x["current_work_evidence"], "unknown")
        self.assertFalse(x["retirement_or_activity_assigned"])

    def test_missing_code_without_secondary_fields_stays_unknown(self):
        x = decode_current_work(None)
        self.assertEqual(x["missing_kind"], "unasked_or_missing_not_identified")
        self.assertIsNone(x["source_no_work_reason_evidence"])

    def test_inconsistent_secondary_inputs_are_not_silently_imputed(self):
        x = decode_current_work(None, last_year_work=1, no_work_reason=3)
        self.assertTrue(x["secondary_source_conflict"])
        self.assertEqual(x["current_work_evidence"], "unknown")

    def test_unrecognized_code_cannot_become_random_job(self):
        x = decode_current_work(9999)
        self.assertEqual(x["current_work_evidence"], "unknown")
        self.assertEqual(x["source_A3100a"], 9999)


if __name__ == "__main__":
    unittest.main()
