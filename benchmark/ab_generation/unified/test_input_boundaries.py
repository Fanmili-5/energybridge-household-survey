import copy
import unittest
from unittest.mock import patch

from .a_solver import solve
from .candidates import generate_day
from .input_boundaries import DOWNSTREAM_FIELDS,require_no_downstream_fields
from .selection import concepts,equivalent_frame
from benchmark.research_delivery.test_semantic_links import fixture


class InputBoundaryTests(unittest.TestCase):
    def test_canonical_fields_reject_even_false_zero_and_empty_values(self):
        for field in sorted(DOWNSTREAM_FIELDS):
            for value in [False,0,'',{},[],{'value':1}]:
                for item in [{field:value},{'outer':[{'nested':({field:value},)}]}]:
                    with self.subTest(field=field,value=value,item=item):
                        with self.assertRaisesRegex(ValueError,'DOWNSTREAM_LABEL_OR_RESULT_IN_TEST'):
                            require_no_downstream_fields(item,'TEST')

    def test_A_rejects_before_model_construction(self):
        for field in sorted(DOWNSTREAM_FIELDS):
            for on_portrait in [False,True]:
                bad={'nested':[{field:0}]}
                with self.subTest(field=field,on_portrait=on_portrait):
                    with patch('benchmark.ab_generation.unified.a_solver.cp_model.CpModel') as model:
                        with self.assertRaisesRegex(ValueError,'DOWNSTREAM_LABEL_OR_RESULT_IN_A_'):
                            solve({} if on_portrait else bad,bad if on_portrait else {})
                        model.assert_not_called()

    def test_B_rejects_before_hash_or_grammar(self):
        for field in sorted(DOWNSTREAM_FIELDS):
            for on_portrait in [False,True]:
                bad={'nested':[{field:False}]}
                with self.subTest(field=field,on_portrait=on_portrait):
                    with patch('benchmark.ab_generation.unified.candidates.digest') as digest:
                        with self.assertRaisesRegex(ValueError,'DOWNSTREAM_LABEL_OR_RESULT_IN_B_'):
                            generate_day({} if on_portrait else bad,portrait=bad if on_portrait else {})
                        digest.assert_not_called()

    def test_nested_label_cannot_disappear_in_equivalent_compression(self):
        for field in sorted(DOWNSTREAM_FIELDS):
            bad={'nested':[{field:''}]}
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError,'DOWNSTREAM_LABEL_OR_RESULT_IN_SELECTION_CANDIDATE'):
                    concepts(bad)
                with self.assertRaisesRegex(ValueError,'DOWNSTREAM_LABEL_OR_RESULT_IN_SELECTION_CANDIDATE'):
                    equivalent_frame([bad],{'seed':0})

    def test_null_placeholders_preserve_features_and_input(self):
        original=fixture();row=copy.deepcopy(original)
        row['extra_nulls']={field:None for field in DOWNSTREAM_FIELDS}
        before=copy.deepcopy(row)
        require_no_downstream_fields(row,'TEST')
        self.assertEqual(concepts(original),concepts(row))
        self.assertEqual(before,row)


if __name__=='__main__':unittest.main()
