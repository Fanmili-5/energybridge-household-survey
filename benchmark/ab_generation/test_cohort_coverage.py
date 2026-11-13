import unittest
from collections import Counter,defaultdict
from copy import deepcopy
from benchmark.ab_generation.cohort_coverage import can_swap,adopt,simple_tokens,_TOKEN_CACHE
from benchmark.ab_generation.unified.test_joint_order_selection import row
class CohortTests(unittest.TestCase):
 def setUp(self):_TOKEN_CACHE.clear()
 def fixture(self):
  old=row(1,'d','old');old['raw_root_cells']=['a'];old['known_event_reduction_kWh']=-1
  new=deepcopy(old);new['id']='new';new['raw_root_cells']=['b']
  state=dict(raw={'r':{'a':{'CN','GB'},'b':{'CN','GB'}}},chosen={'r':defaultdict(Counter,{'a':Counter(CN=2,GB=1),'b':Counter(GB=1)})},base_counts={1:Counter({t:1 for t in simple_tokens(old)})},required={1:simple_tokens(old)})
  return state,dict(index=1,role='r',country='CN',row=old),new
 def test_fills_country_gap_and_preserves_base(self):
  state,slot,new=self.fixture();self.assertTrue(can_swap(state,slot,new));adopt(state,slot,new)
  self.assertEqual(1,state['chosen']['r']['b']['CN']);self.assertEqual(1,state['chosen']['r']['a']['CN'])
 def test_unique_old_country_cannot_be_lost(self):
  state,slot,new=self.fixture();state['chosen']['r']['a']['CN']=1
  self.assertFalse(can_swap(state,slot,new))
 def test_joint_order_cannot_be_lost(self):
  state,slot,new=self.fixture();new=row(2,'d','new-order');new.update(raw_root_cells=['b'],known_event_reduction_kWh=-1)
  self.assertFalse(can_swap(state,slot,new))
 def test_negative_nominal_case_is_not_replaced_with_positive(self):
  state,slot,new=self.fixture();new['known_event_reduction_kWh']=1
  self.assertFalse(can_swap(state,slot,new))
 def test_family_cannot_be_lost(self):
  state,slot,new=self.fixture();new['components'][0]['family']='dishwasher'
  self.assertFalse(can_swap(state,slot,new))
if __name__=='__main__':unittest.main()
