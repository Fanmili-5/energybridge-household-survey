"""IPOG-C base horizontal/vertical growth with a tri-state extension oracle.

Yu et al., ICST 2013, Fig.2. Budget interruption and explicit UNKNOWN are project
extensions; only a completed run can claim the declared finite interaction cover.
The oracle returns a COMPLETE witness, never merely a locally valid partial row.
"""
import itertools
from ..common import digest


def interactions(domains, triples=()):
    n=len(domains)
    axes=set(itertools.combinations(range(n),2))
    axes.update(tuple(sorted(t)) for t in triples)
    if n==1: axes.add((0,))
    for group in sorted(axes,key=lambda t:(len(t),t)):
        for values in itertools.product(*(domains[i] for i in group)):
            yield tuple(zip(group,values))


def covered(row, target):
    return all(row[i]==v for i,v in target)


def round_robin(domains,oracle,*,triples=(),seed=0,row_budget=1000,query_budget=16000):
    """Legacy cardinality round-robin adapted to the SAME finite factor cells.

    Uses the original presence_subsets implementation and cyclic dose indexing.
    Does not copy its old representative truncation or service-success priority;
    those would confound a matched-domain comparison. Not an exact v4 replay.
    """
    from ..collection_candidates import presence_subsets
    active=[i for i,d in enumerate(domains) if len(d)>1]
    subsets=presence_subsets(active,row_budget);rows=[];seen=set();calls=0;cache={}
    for trial in range(max((len(d) for d in domains),default=1)):
        for subset in subsets:
            if calls>=query_budget or len(rows)>=row_budget:break
            assignment={i:0 for i in range(len(domains))}
            for j,i in enumerate(subset):assignment[i]=domains[i][1:][(trial*(j+1)+j)%max(1,len(domains[i])-1)]
            status,witness,reason=oracle(assignment);calls+=1;cache[tuple(sorted(assignment.items()))]=(status,reason)
            if status=='feasible' and tuple(witness) not in seen:rows.append(witness);seen.add(tuple(witness))
        if calls>=query_budget or len(rows)>=row_budget or getattr(oracle,'materializations',0)>=row_budget:break
    ledger=[]
    for t in interactions(domains,triples):
        hit=next((i for i,r in enumerate(rows) if covered(r,t)),None)
        ledger.append(dict(target=[list(x) for x in t],status='feasible' if hit is not None else 'unexplored',
            witness_row=hit,reason=None if hit is not None else 'round_robin_budget;not_infeasibility'))
    return dict(rows=rows,coverage=ledger,queries=calls,complete=all(r['witness_row'] is not None for r in ledger),
                method='legacy_cardinality_round_robin_same_domain_adapter_not_exact_v4')


def generate(domains, oracle, *, triples=(), seed=0, row_budget=1000, query_budget=16000):
    """Return rows and every predeclared target, including unqueried targets.

    Horizontal growth extends compatible prefixes; vertical growth covers the
    remaining target tuples. Caching removes duplicate existential queries.
    Witnesses for all joint orders are requested by the caller, not confused
    with pairwise interaction strength.
    """
    domains=[list(d) for d in domains]
    if any(not d for d in domains): raise ValueError('EMPTY_FACTOR_DOMAIN')
    targets=list(interactions(domains,triples)); target_set=set(targets)
    groups=sorted({tuple(i for i,_ in t) for t in targets})
    rows=[];row_set=set();hits={};cache={}; calls=0
    def ask(partial):
        nonlocal calls
        key=tuple(sorted(partial.items()))
        if key in cache: return cache[key]
        if calls>=query_budget: return ('unknown',None,'query_budget')
        calls+=1
        answer=oracle(dict(key))
        if answer[0] not in ('feasible','infeasible','unknown'):
            raise ValueError('INVALID_ORACLE_STATUS')
        if answer[0]=='feasible' and (len(answer[1])!=len(domains) or
            not all(answer[1][i] in domains[i] for i in range(len(domains))) or
            not all(answer[1][i]==v for i,v in key)):
            raise ValueError('ORACLE_WITNESS_DOES_NOT_EXTEND_TARGET')
        cache[key]=answer
        return answer
    def add(row):
        value=tuple(row)
        if value not in row_set and len(rows)<row_budget:
            index=len(rows);rows.append(value);row_set.add(value)
            for group in groups:
                target=tuple((i,value[i]) for i in group)
                if target in target_set:hits.setdefault(target,index)
    n=len(domains)
    if n==0:return dict(rows=[],coverage=[],queries=0,complete=True)
    # IPOG starts with the first t parameters, then horizontal/vertical growth.
    t=min(2,n)
    prefixes=[]
    for vals in itertools.product(*domains[:t]):
        if calls>=query_budget or len(rows)>=row_budget: break
        status,witness,_=ask(dict(enumerate(vals)))
        if status=='feasible':prefixes.append(dict(enumerate(vals)));add(witness)
    for k in range(t,n):
        next_prefix=[]
        relevant=[target for target in targets if max(i for i,_ in target)==k]
        for partial in prefixes:
            if calls>=query_budget:break
            def gain(v):
                row={**partial,k:v}
                ts=[tuple((i,row[i]) for i in group) for group in groups if k in group and all(i in row for i in group)]
                return sum(u in target_set and u not in hits for u in ts)
            options=sorted(domains[k],key=lambda v:(-gain(v),digest([seed,k,v])))
            for v in options:
                status,witness,_=ask({**partial,k:v})
                if status=='feasible':next_prefix.append({**partial,k:v});add(witness);break
        prefixes=next_prefix
        # Vertical growth: each feasible uncovered tuple receives a witness.
        for target in relevant:
            if target in hits:continue
            if calls>=query_budget or len(rows)>=row_budget:break
            status,witness,_=ask(dict(target))
            if status=='feasible':add(witness)
    # Complete the explicit mixed-strength universe, including initial factors.
    for target in targets:
        if target in hits:continue
        if calls>=query_budget or len(rows)>=row_budget:break
        status,witness,_=ask(dict(target))
        if status=='feasible':add(witness)
    ledger=[]
    for target in targets:
        answer=cache.get(target)
        status='feasible' if target in hits else answer[0] if answer else 'unexplored'
        ledger.append(dict(target=[list(x) for x in target],status=status,
            witness_row=hits.get(target),
            reason=None if target in hits else answer[2] if answer else 'search_budget_or_not_yet_queried'))
    return dict(rows=[list(x) for x in rows],coverage=ledger,queries=calls,
        complete=all(x['status']=='infeasible' or x['witness_row'] is not None for x in ledger),
        method='IPOG-C_base_with_complete_extension_oracle_and_budgeted_mixed_strength_completion',
        row_budget=row_budget,query_budget=query_budget)
