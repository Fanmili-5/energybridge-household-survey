"""Bounded propagation and MRV search on unchanged native index sets.

Full literal validation still follows each complete assignment.
"""
from .interval_propagation import propagate


def assignments(allowed,holds,fixed,parents,operations,roots,order,budget,stats):
    stats.update(nodes=0,empty_branches=0,complete=False,budget_exhausted=False)
    def visit(domains):
        if stats['nodes']>=budget:
            stats['budget_exhausted']=True;return
        stats['nodes']+=1
        reduced,proof=propagate(domains,holds,fixed,parents,operations,roots,order)
        if proof['empty']:
            stats['empty_branches']+=1;return
        free=[i for i,ids in reduced.items() if len(ids)>1]
        if not free:
            yield [reduced[i][0] for i in sorted(reduced)];return
        i=min(free,key=lambda i:(len(reduced[i]),i))
        # Unchanged first, then direct event paths, then conditional supports.
        # No successful response, energy saving or predicted acceptance rank.
        for v in sorted(reduced[i],key=lambda j:(j!=0,j not in roots[i],j)):
            if stats['budget_exhausted']:return
            yield from visit({**reduced,i:[v]})
    yield from visit(allowed)
    stats['complete']=not stats['budget_exhausted']
