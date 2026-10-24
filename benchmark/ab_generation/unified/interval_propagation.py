"""Sound interval-domain filtering before bounded literal/CP search.

This is bounds-support propagation for machine holds and wash/dry precedence.
No calendar, service-success, consent, energy or answer objective is inspected.
Nonempty domains do not prove a simultaneous feasible assignment.
"""


def propagate(allowed, holds, fixed, parents, operations, roots, order=None):
    domains={i:list(ids) for i,ids in allowed.items()};removed=0;rounds=0
    by_need={h['need_id']:i for i,h in holds.items()}
    fixed_end={o['need_id']:o['end_min'] for o in operations if o['kind']=='unload'}
    while True:
        rounds+=1;before=sum(map(len,domains.values()))
        # Only a single possibly active factor can be required to be a root.
        root_factors=[i for i,ids in domains.items() if any(j in roots[i] for j in ids)]
        if not root_factors:return domains,dict(empty=True,reason='no_event_root_in_query_domain',removed=removed,rounds=rounds)
        if len(root_factors)==1:
            i=root_factors[0];domains[i]=[j for j in domains[i] if j in roots[i]]
        if order is not None:
            forced=sum(0 not in ids for ids in domains.values())
            possible=sum(any(j!=0 for j in ids) for ids in domains.values())
            if not forced<=order<=possible:return domains,dict(empty=True,reason='joint_cardinality_incompatible',removed=removed,rounds=rounds)
            if forced==order:
                for i,ids in domains.items():
                    if 0 in ids:domains[i]=[0]
            elif possible==order:
                for i,ids in domains.items():
                    if any(j!=0 for j in ids):domains[i]=[j for j in ids if j!=0]
        if any(not ids for ids in domains.values()):
            return domains,dict(empty=True,reason='empty_native_query_domain',removed=removed,rounds=rounds)
        extrema={i:(min(h['values'][j][1] for j in domains[i]),max(h['values'][j][1] for j in domains[i]),
                    min(h['values'][j][2] for j in domains[i]),max(h['values'][j][2] for j in domains[i]))
                 for i,h in holds.items()}
        for i,h in holds.items():
            nid,aid=h['need_id'],h['asset_id'];kept=[]
            for j in domains[i]:
                _,start,end,_=h['values'][j]
                if any(aid==a and max(start,b)<min(end,z) for a,b,z,_ in fixed):continue
                parent=parents.get(nid)
                if parent and parent not in by_need and parent in fixed_end and start<fixed_end[parent]:continue
                supported=True
                for k,other in holds.items():
                    if k==i:continue
                    _,latest_start,earliest_end,_=extrema[k]
                    if parent==other['need_id']:
                        supported=start>=earliest_end
                    elif parents.get(other['need_id'])==nid:
                        supported=end<=latest_start
                    elif aid==other['asset_id']:
                        supported=end<=latest_start or start>=earliest_end
                    else:continue
                    if not supported:break
                if supported:kept.append(j)
            domains[i]=kept
        after=sum(map(len,domains.values()));removed+=before-after
        if any(not ids for ids in domains.values()):
            return domains,dict(empty=True,reason='interval_constraints_empty_query_domain',removed=removed,rounds=rounds)
        if before==after:return domains,dict(empty=False,reason=None,removed=removed,rounds=rounds)
