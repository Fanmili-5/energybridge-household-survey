"""Check persona alignment and prevent attitude leakage into household classes."""
import ast
import copy
import unittest
from common import UPSTREAM, PROPOSAL_PROFILE_QUESTIONS, normalize_answers, profile_text
from questionnaire_persona import ATTITUDES, components, visible_profile

class QuestionnaireTests(unittest.TestCase):
    def normalize(self, values):
        questions={q["id"]:q for q in PROPOSAL_PROFILE_QUESTIONS}
        return normalize_answers(values,list(questions),questions)

    def test_exact_eb_generator_values_and_explicit_factual_exception(self):
        source=ast.parse((UPSTREAM/'energybridge/roleplay/schema.py').read_text())
        valid=next(ast.literal_eval(n.value) for n in source.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='VALID_TAGS')
        for q in ATTITUDES:
            values={o['value'] for o in q['options']}
            expected=set(valid[q['eb_dimension']])
            if q['eb_dimension']=='task':expected.remove('ev_constrained')
            self.assertEqual(values,expected)

    def test_classification_inputs_do_not_change_with_attitude_or_contain_decision(self):
        a=self.normalize({'B02':'3','B05':['ac','washer'],'F_REGULARITY':'regular','A_EB_COMFORT':'temp_sensitive'})
        b=copy.deepcopy(a);b['A_EB_COMFORT']['value']='temp_tolerant'
        left,right=(components(p,PROPOSAL_PROFILE_QUESTIONS) for p in [a,b])
        self.assertEqual(left['classification'],right['classification'])
        self.assertNotEqual(left['eb_attitudes'],right['eb_attitudes'])
        self.assertIsNone(left['classification']['household_type'])
        self.assertNotIn('A_EB_COMFORT',left['classification']['features'])
        self.assertEqual(left['eb_attitudes']['price']['response_status'],'skipped')
        self.assertIsNone(left['eb_attitudes']['price']['value'])

    def test_facts_do_not_assign_attitudes_and_public_text_has_no_synthetic_weights(self):
        p=self.normalize({'B02':'2','B05':['home_ev'],'F_LATE_USE':'often'})
        c=components(p,PROPOSAL_PROFILE_QUESTIONS)
        self.assertTrue(all(v['value'] is None for v in c['eb_attitudes'].values()))
        self.assertNotIn('scoring_weights',c['eb_attitudes'])
        self.assertNotIn('grid_value',c['eb_attitudes'])
        p=self.normalize({'B05':['ac'],'A_EB_CONTROL':'confirm_required'})
        visible=visible_profile(p,PROPOSAL_PROFILE_QUESTIONS)
        self.assertTrue(any('明确确认' in (r['answer'] or '') for r in visible['stated_attitudes']))
        self.assertIn('明确确认',profile_text(p))
        for answers in ({'A03':5},{'A_EB_CONTROL':'dont_know'}):
            with self.assertRaises(ValueError):self.normalize(answers)

if __name__=='__main__':unittest.main()
