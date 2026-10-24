import tempfile
import unittest
from pathlib import Path

from benchmark.ab_generation.common import save,sha,seal
from benchmark.ab_generation.unified.contract import code_hash
from .literal_bank_review import inspect_rows,run


def context():
    return dict(A=dict(tasks=[],operations=[],controls=[]),devices=[],needs=[],decision_min=480,horizon_min=[480,1920])


class LiteralBankReviewTests(unittest.TestCase):
    def test_equal_count_does_not_hide_duplicate_id_or_missing_date(self):
        contexts={('h','d1'):context(),('h','d2'):context()}
        rows=[dict(id='same',household_id='h',date='d1',patches=[])]*2
        result=inspect_rows(rows,contexts)
        self.assertFalse(result['passed']);self.assertEqual(['same'],result['duplicate_case_ids'])
        self.assertEqual([['h','d2']],result['missing_given_dates'])

    def test_unexpected_date_is_diagnostic_not_replacement(self):
        row=dict(id='x',household_id='h',date='wrong',patches=[])
        result=inspect_rows([row],{('h','original'):context()})
        self.assertFalse(result['passed']);self.assertEqual(['UNDECLARED_SOURCE_DATE'],result['engineering_errors'][0]['errors'])
        self.assertEqual([['h','original']],result['missing_given_dates'])

    def test_source_mutation_is_rejected_before_row_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bank=root/'bank';bank.mkdir();cp=root/'context.json';ip=root/'input.json'
            save(cp,context());save(ip,dict(schema='eb.unified.inputs.v1',records=[dict(household_id='h',date='d',context_path=str(cp))]))
            save(bank/'PRE_GENERATION.json',dict(code_sha256='original_generator',source_sha256={str(ip):sha(ip),str(cp):sha(cp)}))
            save(bank/'GENERATION.json',[dict(household_id='h',date='d')])
            save(bank/'CANDIDATE_ROWS.json.gz',[dict(id='x',household_id='h',date='d',patches=[])])
            seal(bank,dict(schema='eb.frozen_catalogue_linked_selection.v1'))
            save(cp,{**context(),'mutated':True})
            result=run(bank,root/'review',code_hash())
            self.assertFalse(result['passed']);self.assertEqual('SOURCE_CHANGED_BEFORE_LITERAL_REVIEW',result['admission_error'])


if __name__=='__main__':unittest.main()
