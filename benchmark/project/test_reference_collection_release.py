"""Meaningful pending-outcome wording without changing the approved form schema."""
import unittest
from .questionnaire import COLLECTOR
from .reference_collection_release import proposal_question_copy

class ProposalQuestionCopyTest(unittest.TestCase):
    def test_pending_scores_are_about_observed_plan_requests(self):
        original=(COLLECTOR/'index.html').read_text();changed=proposal_question_copy(original)
        self.assertNotIn('用电量变化是否适合',changed)
        self.assertNotIn('室温与生活变化是否适合',changed)
        self.assertIn('不推测尚未计算的用电量、室温或VPP达标情况',changed)
        for key in ['score','comfort_score','energy_score','vpp_score']:
            self.assertEqual(original.count('id="'+key+'"'),changed.count('id="'+key+'"'))
        for contract in ['min="1" max="5" step="0.1"','required','接受B方案','不接受B方案']:
            self.assertEqual(original.count(contract),changed.count(contract))

    def test_changed_upstream_wording_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'V69_PROPOSAL_QUESTION_ANCHOR_CHANGED'):
            proposal_question_copy('<html>unknown form</html>')

if __name__=='__main__':unittest.main()
