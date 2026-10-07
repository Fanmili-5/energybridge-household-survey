"""Enumerate equipment support against fixed walls, beds, portals and service fixtures."""
import ast, collections, copy, itertools, math
from common import *
from shapely.geometry import box, Point
from shapely.ops import unary_union
# Reuse the reviewed door-connectivity algorithm, not an area-only fit heuristic.
source = BASE / 'joint_housing_service_worlds_20261006/code/service_ports.py'
# Source is pinned in INPUT_LOCK. A copy is staged when the older code is unavailable.
if not source.exists(): source = OUT / 'inputs/service_ports_source.py'
tree = ast.parse(source.read_text())
fs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ['reach', 'place']]
WORKTOP_SOURCE = 'https://www.ikea.com/at/en/p/lilltraesk-worktop-white-laminate-00479874/'
SIZES = {'worktop': (1.23,.635,0), 'laundry': (.596,.637,.418), 'dishwasher': (.6,.6,.4),
         'toilet': (.4,.7,0), 'shower': (.8,.8,0), 'tank': (.39,.39,0)}
exec(compile(ast.Module(body=fs,type_ignores=[]), str(source), 'exec'), globals())
class EnumeratePlacements(ast.NodeTransformer):
    def visit_Return(self,node):
        if isinstance(node.value,ast.Dict):return ast.copy_location(ast.Expr(ast.Yield(node.value)),node)
        return node
pf=copy.deepcopy(next(n for n in fs if n.name=='place'));pf.name='place_options'
pf=EnumeratePlacements().visit(pf);ast.fix_missing_locations(pf)
exec(compile(ast.Module(body=[pf],type_ignores=[]),str(source),'exec'),globals())
def solve_backtracking(requests,dd,bed_obs,bed_sites,target,max_nodes=10000):
    nodes=0
    def solve(index,obs,sites,placed):
        nonlocal nodes
        if index==len(requests):return placed
        kind,options=requests[index]
        for room in options:
            rid=room['room_id']
            if rid not in dd:continue
            for p in place_options(room,dd[rid],kind,obs[rid],sites[rid]):
                nodes+=1
                if nodes>max_nodes:return None
                no=copy.deepcopy(obs);ns=copy.deepcopy(sites)
                no[rid].append(p['operation_envelope_rect_m']);ns[rid].append(p['reachable_operator_center_m'])
                found=solve(index+1,no,ns,placed+[p])
                if found:return found
        return None
    return solve(0,copy.deepcopy(bed_obs),copy.deepcopy(bed_sites),[])
def doors(rows):
    parents = {r[1]:r[4] for r in rows if r[0]=='BuildingSurface:Detailed'}
    return {parents[r[4]]:[list(map(float,r[j:j+3])) for j in range(10,len(r),3)]
            for r in rows if r[0]=='FenestrationSurface:Detailed' and r[2]=='Door'
            and not r[1].endswith('_peer') and r[1]!='entry_door'}
def patterns():
    return [list(c) for n in [4,5,6] for c in itertools.combinations(sorted(KINDS),n)
            if 'dryer' not in c or 'washer' in c]
def candidates(w, rows, deep=False):
    hid=w['household_id'];target=[r for r in w['layout']['rooms'] if hid in r['using_household_ids']]
    dd=doors(rows);bed_obs=collections.defaultdict(list);bed_sites=collections.defaultdict(list)
    frames=w['layout']['sleep_reference']['frames']
    for f in frames:bed_obs[f['room_id']].append(f['outer_rect_m'])
    # Prior witnesses include a canonical (pre-scaling) access coordinate. Do not
    # interpret that coordinate as a point in the finished metric floorplan.
    for f in frames:
        room=next(r for r in target if r['room_id']==f['room_id']);x0,y0,x1,y1=f['outer_rect_m']
        if y1-y0>=x1-x0:sites=[(x0-.30001,(y0+y1)/2),(x1+.30001,(y0+y1)/2)]
        else:sites=[((x0+x1)/2,y0-.30001),((x0+x1)/2,y1+.30001)]
        viable=[s for s in sites if f['room_id'] in dd and reach(room,dd[f['room_id']],bed_obs[f['room_id']],s)]
        if not viable:return [],[{'reason':'NO_METRIC_BED_ACCESS','frame_id':f['frame_id']}]
        bed_sites[f['room_id']].append(viable[0])
    adult=any(m['age_years']>=18 for m in w['members'])
    kitchens=[r for r in target if r['census_room_class']=='kitchen']
    services=[r for r in target if r['census_room_class']=='non_H7_service']
    alcoves=[r for r in target if r['census_room_class']=='hall'] if deep else []
    if not services: return [], [{'reason':'NO_SERVICE_ROOM'}]
    # Small spaces are solved before large ones; fixtures cannot be silently removed.
    room_order=sorted(services+kitchens,key=lambda r:(r['census_room_class']=='kitchen',r['usable_area_m2']))
    results=[];failures=[]
    for kinds in patterns():
        if 'ev' in kinds and not adult:continue
        if 'dishwasher' in kinds and not kitchens:continue
        requests=[]
        for r in kitchens: requests.append(('worktop',[r]))
        if w['layout']['stock_reference_features']['toilet']!='none':requests.append(('toilet',services))
        if 'water_heater' in kinds:requests.extend([('shower',services),('tank',services+alcoves)])
        if 'washer' in kinds:requests.append(('laundry',room_order+alcoves))
        if 'dishwasher' in kinds:requests.append(('dishwasher',kitchens))
        found=None
        # Backtracking room/order permutations are prespecified, independent of energy results.
        for order in [requests,sorted(requests,key=lambda x:-(SIZES[x[0]][0]*SIZES[x[0]][1]))]:
            obs=copy.deepcopy(bed_obs);sites=copy.deepcopy(bed_sites);placed=[];ok=True
            for kind,options in order:
                p=None
                for room in options:
                    rid=room['room_id']
                    if rid not in dd:continue
                    p=place(room,dd[rid],kind,obs[rid],sites[rid])
                    if p:break
                if not p:ok=False;break
                p['reference_dimension_source'] = WORKTOP_SOURCE if kind=='worktop' else (
                    'DEVICE_MODEL_CATALOG.Miele_WTD160 outer/door geometry;EB program is a separate functional reference' if kind=='laundry'
                    else 'EB native cylinder volume/height,rounded enclosing square' if kind=='tank'
                    else 'explicit reference fixture dimension;not a product certification')
                obs[p['room_id']].append(p['operation_envelope_rect_m']);sites[p['room_id']].append(p['reachable_operator_center_m']);placed.append(p)
            if ok and all(reach(r,dd[r['room_id']],obs[r['room_id']],s) for r in target if r['room_id'] in dd for s in sites[r['room_id']]):
                found=placed;break
        if not found and deep:
            found=solve_backtracking(requests,dd,bed_obs,bed_sites,target)
            if found:
                for p in found:p['reference_dimension_source']='prespecified reference dimensions;laundry geometry from OEM catalog;native tank cylinder envelope'
        if found:results.append({'types':kinds,'placements':found,
            'sleep_metric_access_witnesses':dict(bed_sites)})
        else:failures.append({'types':kinds,'reason':'NO_NONOVERLAP_AND_PORTAL_REACH_WITNESS'})
    if not results and not deep:return candidates(w,rows,deep=True)
    return results,failures
