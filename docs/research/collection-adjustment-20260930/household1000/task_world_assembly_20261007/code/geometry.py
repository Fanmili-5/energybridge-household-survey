"""Door-aware appliance placement; preserve existing sleeping witnesses."""
import ast
from common import *
from shapely.geometry import box,Point
from shapely.ops import unary_union
SOURCE=V10/'code/service_ports.py'
tree=ast.parse(SOURCE.read_text());functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['reach','place']]
# Exact source functions; added device shapes are explicit reference dimensions.
SIZES={'washer':(.6,.6,.4),'dishwasher':(.6,.6,.4)}
exec(compile(ast.Module(body=functions,type_ignores=[]),str(SOURCE),'exec'),globals())
def doors(path):
    rows=parse(path);parents={r[1]:r[4] for r in rows if r[0]=='BuildingSurface:Detailed'}
    return {parents[r[4]]:[list(map(float,r[j:j+3])) for j in range(10,len(r),3)] for r in rows if r[0]=='FenestrationSurface:Detailed' and r[2]=='Door' and not r[1].endswith('_peer') and r[1]!='entry_door'}

def fitted(room,door,kind,obstacles,protected):
    result=place(room,door,kind,obstacles,protected)
    if result:result['reference_dimension_source']='explicit600x600mm assembly fixture and400mm opening envelope;not manufacturer-specific hardware'
    return result
