import itertools
import unittest
from .interval_propagation import propagate


class IntervalPropagationTests(unittest.TestCase):
    def test_no_valid_solution_lost_against_independent_small_enumerator(self):
        holds={i:dict(asset_id='same' if i<2 else 'dryer',need_id=str(i),
                     values=[[j,20*j+10*i,20*j+10*i+10,20*j+10*i+5] for j in range(3)]) for i in range(3)}
        roots={0:{1},1:{2},2:set()};subsets=[[0],[1],[2],[0,1],[1,2],[0,2],[0,1,2]]
        checked=0
        for ds in itertools.product(subsets,repeat=3):
            for order in (None,1,2,3):
                for dependency in (False,True):
                    parents={'2':'0'} if dependency else {};valid=[]
                    for x in itertools.product(*ds):
                        if not any(v in roots[i] for i,v in enumerate(x)):continue
                        if order is not None and sum(v!=0 for v in x)!=order:continue
                        a,z=20*x[0],20*x[0]+10;b,y=20*x[1]+10,20*x[1]+20
                        if max(a,b)<min(z,y):continue
                        if dependency and 20*x[2]+20<z:continue
                        valid.append(x)
                    filtered,proof=propagate(dict(enumerate(ds)),holds,[],parents,[],roots,order)
                    self.assertTrue(all(all(v in filtered[i] for i,v in enumerate(x)) for x in valid))
                    if proof['empty']:self.assertFalse(valid)
                    checked+=1
        self.assertEqual(checked,2744)

    def test_fixed_batch_hold_and_parent_are_not_discarded(self):
        h={0:dict(asset_id='washer',need_id='child',values=[[0,10,30,20],[1,40,60,50]])}
        d,p=propagate({0:[0,1]},h,[('washer',20,40,'fixed')],{'child':'parent'},
                      [dict(need_id='parent',kind='unload',end_min=35)],{0:{1}})
        self.assertEqual(d[0],[1]);self.assertFalse(p['empty'])

    def test_empty_intersection_is_not_a_witness(self):
        from .contract import config
        from .candidates import Oracle
        from .exhaustive import fixtures
        _,c,_,_=next(fixtures());task=c['A']['tasks'][0]
        changed={**task,'start_min':task['start_min']+10,'end_min':task['end_min']+10}
        raw=dict(family='washer',asset_id=task['asset_id'],service_need_id=task['need_id'],
                 profiles={'A':[task],'B':[changed]},patches=[dict(type='rows',collection='tasks',identity='task_id',rows=[changed]),
                 dict(type='rows',collection='operations',identity='operation_id',rows=[o for o in c['A']['operations'] if o['need_id']==task['need_id']])])
        g=dict(values=[[None,raw]],descriptors=[[dict(ids=[0]),dict(ids=[1])]],domains=[[0,1]])
        for mode in ('none','interval_v1','interval_forward_v1'):
            oracle=Oracle(c,g,config({'oracle_propagation':mode}),None)
            status,_,_=oracle({0:0},native_required={0:[1]})
            self.assertEqual(status,'infeasible');self.assertEqual(oracle.materializations,0)


if __name__=='__main__':unittest.main()
