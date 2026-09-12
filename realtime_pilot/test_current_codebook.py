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


if __name__=='__main__':unittest.main()
