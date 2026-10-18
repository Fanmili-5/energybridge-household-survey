"""Source-preserving contiguous face merge."""
import collections,copy

def merge(walls):
    groups=collections.defaultdict(list)
    for w in walls:
        v=w['vertices'];axis=0 if max(p[0]for p in v)-min(p[0]for p in v)>.0001 else 1
        key=(w['zone'],w['peer_zone'],w['side'],w['bc'],w['construction'],axis,
             round(v[0][1-axis],8),min(p[2]for p in v),max(p[2]for p in v))
        groups[key].append(w)
    out=[]
    for key,values in groups.items():
        axis=key[5];values.sort(key=lambda w:min(p[axis]for p in w['vertices']));current=None;low=high=None
        for w in values:
            a=min(p[axis]for p in w['vertices']);b=max(p[axis]for p in w['vertices'])
            if current is not None and abs(a-high)<1e-7:
                for p in current['vertices']:
                    if abs(p[axis]-high)<1e-7:p[axis]=b
                high=b
            else:
                if current is not None:out.append(current)
                current=copy.deepcopy(w);low,high=a,b
        if current is not None:out.append(current)
    return out
