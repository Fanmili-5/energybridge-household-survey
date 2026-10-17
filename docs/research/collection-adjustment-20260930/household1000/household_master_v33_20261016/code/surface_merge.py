"""Merge contiguous coplanar shell faces before placing doors and windows.

An opposite room's partition line must not split a continuous gallery wall into
sub-door fragments. Pairwise interior faces are merged before peer assignment.
"""
import ast,collections,copy
from pathlib import Path


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


def install(compiler,path):
    tree=ast.parse(Path(path).read_text());function=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='model')
    class Patch(ast.NodeTransformer):
        count=0
        def visit_Assign(self,node):
            if any(isinstance(t,ast.Name)and t.id=='signatures'for t in node.targets):
                self.count+=1
                return [ast.parse('walls=merge_reference_faces(walls)').body[0],node]
            return node
    patch=Patch();function=patch.visit(function)
    if patch.count!=1:raise ValueError('SHELL_KERNEL_FACE_MERGE_HOOK_CHANGED')
    module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    compiler.__dict__['merge_reference_faces']=merge
    exec(compile(module,str(path),'exec'),compiler.__dict__)
    return compiler
