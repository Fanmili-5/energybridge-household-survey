"""The published data dictionary must be identical to the live runtime contract."""
import json
import unittest

from common import STUDY, digest
from paired_contract import CONTEXT, QUESTIONNAIRE_VERSION, QUESTIONS, VERSION
from proposal_contract import FEEDBACK_VERSION, SCORE_FIELDS


class CurrentCodebookTests(unittest.TestCase):
    def test_published_codebook_matches_runtime(self):
        data=json.loads((STUDY/'QUESTIONNAIRE_CODEBOOK.json').read_text())
        self.assertEqual(data['status'],'runtime_authoritative')
        self.assertEqual(data['schema_version'],QUESTIONNAIRE_VERSION)
        self.assertEqual(data['paired_flow_version'],VERSION)
        self.assertEqual(data['questions'],QUESTIONS)
        self.assertEqual(data['questions_sha256'],digest(QUESTIONS))
        self.assertEqual(data['tariff'],CONTEXT['tariff'])
        self.assertEqual(data['feedback_contract']['version'],FEEDBACK_VERSION)
        self.assertEqual(data['feedback_contract']['score_fields'],list(SCORE_FIELDS))
        self.assertTrue(data['feedback_contract']['comment_required'])
        self.assertEqual(data['scenario_sampling']['event_duration_hours'],[1,2])

    def test_requiredness_distinguishes_truthful_intake_from_simulation_readiness(self):
        lookup={q['id']:q for q in QUESTIONS}
        for qid in ('B02','B04','B05','F_EVENING'):
            self.assertTrue(lookup[qid]['required_for_intake'])
            self.assertTrue(lookup[qid]['required_for_generation'])
        for qid in ('X_REGION','X_CITY','X_BUILDING','X_AREA','X_AREA_BASIS','X_FLOOR'):
            self.assertFalse(lookup[qid]['required_for_intake'])
            self.assertTrue(lookup[qid]['required_for_generation'])
        self.assertFalse(lookup['X_INCOME']['required_for_intake'])
        self.assertFalse(lookup['X_INCOME']['required_for_generation'])
        self.assertEqual(lookup['H_washer']['required_when'],{'selected_device':'washer'})


if __name__=='__main__':unittest.main()
