import unittest
from .axis_matrix import matrix


def row(identity,home,shift,handling,repeat=1):
    return dict(id=identity,household_id=home,date='day',components=[dict(family='washer',change_axes=dict(
        machine={'signed_start_shift_min':shift},handling={'maximum_absolute_retime_min':handling})) for _ in range(repeat)])


class DescriptivePairCoverageTests(unittest.TestCase):
    def test_marginal_axes_do_not_imply_joint_coverage(self):
        rows=[row('a','h',10,200),row('b','h',200,10),row('c','h',10,10)]
        result=matrix(rows,['a','b'])
        self.assertEqual((3,2,1),(result['available_pairs'],result['selected_pairs'],result['missing_pairs']))
        self.assertFalse(result['selector_or_inputs_changed'])

    def test_repeated_components_are_not_counted_as_independent_cases(self):
        result=matrix([row('a','h',10,10,2)],['a'])['pairs'][0]
        self.assertEqual(2,result['candidate_action_instances'])
        self.assertEqual(1,result['candidate_cases'])
        self.assertEqual(1,result['selected_cases'])

    def test_household_conditioning_preserves_a_local_gap(self):
        rows=[row('a','h1',10,10),row('b','h2',10,10)]
        self.assertEqual(0,matrix(rows,['a'])['missing_pairs'])
        self.assertEqual(1,matrix(rows,['a'],household=True)['missing_pairs'])


if __name__=='__main__':unittest.main()
