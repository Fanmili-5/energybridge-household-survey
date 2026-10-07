"""Audit saved worlds, saved plans and actual compiled IDFs; no generator execution."""
import collections, concurrent.futures, math, platform
from common import *
from validate import validate
SCHEMA=read(SCHEMA_PATH)['properties']
def values(row):return dict(zip(SCHEMA[row[0]]['legacy_idd']['fields'],row[1:]))
def schema_errors(rows):
    errors=[];refs=collections.defaultdict(set);named=set()
    for r in rows:
        if r[0] not in SCHEMA:errors.append('UNKNOWN_OBJECT:'+r[0]);continue
        s=SCHEMA[r[0]];name=s.get('name')
        if name and r[1]:
            key=(r[0].lower(),r[1].lower())
            if key in named:errors.append('DUPLICATE_NAME:'+str(key))
            named.add(key)
            for group in name.get('reference',[]):refs[group].add(r[1].lower())
            for group in name.get('reference-class-name',[]):refs[group].add(r[0].lower())
    for r in rows:
        if r[0] not in SCHEMA:continue
        s=SCHEMA[r[0]];ps=next(iter(s['patternProperties'].values()))['properties']
        for field,value in values(r).items():
            if not value or field not in ps:continue
            f=ps[field]
            if f.get('data_type')=='object_list':
                groups=f['object_list'];allrefs=set().union(*(refs[g] for g in groups))
                if value.lower() not in allrefs:errors.append('MISSING_REFERENCE:'+r[0]+':'+field+':'+value)
            options=f.get('anyOf',[f]);valid=False
            for option in options:
                typ=option.get('type')
                if typ in ['number','integer']:
                    try:
                        v=float(value)
                        if not math.isfinite(v):continue
                        if typ=='integer' and int(v)!=v:continue
                        if 'minimum' in option and v<option['minimum']:continue
                        if 'maximum' in option and v>option['maximum']:continue
                        if 'exclusiveMinimum' in option and v<=option['exclusiveMinimum']:continue
                        if 'exclusiveMaximum' in option and v>=option['exclusiveMaximum']:continue
                        valid=True
                    except ValueError:pass
                else:
                    enum=option.get('enum')
                    if enum is None or value.lower() in [str(x).lower() for x in enum]:valid=True
            if not valid:errors.append('SCHEMA_VALUE:'+r[0]+':'+field+':'+value)
    return sorted(set(errors))
def schedule_at(row,date,minute):
    # Parse the saved compact schedule independently of the schedule writer.
    md=(date.month,date.day);selected=False;i=3
    while i<len(row):
        key=row[i].lower()
        if key.startswith('through:'):
            end=tuple(map(int,key.split(':',1)[1].split('/')))
            if not selected and md<=end:selected=True
            elif selected:return None
            i+=1
        elif key.startswith('until:'):
            hh,mm=map(int,key.split(':',1)[1].split(':'));end=hh*60+mm
            if selected and minute<end:return float(row[i+1])
            i+=2
        else:i+=1
    return None
def audit_one(b):
    w=read(OUT/b['world_path']);old=read(OLD/'worlds'/f'{w["household_id"]}.json');errors=[];counts=collections.Counter()
    for k in ['household_id','province','population_weight','N','G','H6','H7','members','ego_relationships','random10_date_selection']:
        if w[k]!=old[k]:errors.append('ANCHOR_CHANGED:'+k)
    if len(w['members'])!=w['N']:errors.append('ROSTER_N')
    if digest(w['parameter_pack'])!=w['parameter_pack_sha256']:errors.append('PARAMETER_PACK_HASH')
    if w['parameter_pack']['control_defaults']!={k:a['config'] for k,a in w['assets'].items()}:errors.append('DUPLICATED_CONTROL_DEFAULTS_CHANGED')
    wc=dict(w);claimed=wc.pop('world_content_sha256')
    if digest(wc)!=claimed or sha(OUT/b['world_path'])!=b['world_sha256']:errors.append('WORLD_HASH')
    if not 4<=len({k for d in w['parameter_pack']['devices'] for k in d['types']})<=6:errors.append('K_COUNT')
    dates=w['random10_date_selection']['dates']
    if len(dates)!=10 or len({x['date'] for x in dates})!=10:errors.append('DATE_COUNT')
    # Compare the produced artifact against independent old bindings and whole-unit allocations.
    if abs(w['layout']['allocated_gross_area_by_context_household_m2'][w['household_id']]-w['H6'])>1e-5:errors.append('H6_ALLOCATION')
    phys_hash=None
    for index in range(1,11):
        pp=OUT/'pairs'/w['household_id']/f'{index:02d}.json';p=read(pp);errors+=validate(p)
        if p['date']!=dates[index-1]['date']:errors.append('DATE_RESELECTED')
        if p['world_sha256']!=w['world_content_sha256']:errors.append('PAIR_WORLD_BINDING')
        if p['world']['devices']!=w['parameter_pack']['devices']:errors.append('PAIR_DEVICE_PARAMETERS_CHANGED')
        if p['world']['circuit_limit_kw']!=w['parameter_pack']['circuit_limit_kw']:errors.append('PAIR_CIRCUITS_CHANGED')
        binding=b['compiled_records'][index-1]
        if sha(pp)!=binding['pair_sha256']:errors.append('SAVED_PAIR_HASH')
        rowsA=parse(OUT/'idfs'/w['household_id']/f'{index:02d}_A.idf');rowsB=parse(OUT/'idfs'/w['household_id']/f'{index:02d}_B.idf')
        for side,rows in [('A',rowsA),('B',rowsB)]:
            if sha(OUT/binding[side]['IDF_path'])!=binding[side]['IDF_sha256']:errors.append('SAVED_IDF_HASH')
            errors+=schema_errors(rows)
            # Physical objects, geometry and constant setpoints must be identical across
            # every date and both arms. Only compact schedules and RunPeriod vary.
            physical=[r for r in rows if r[0] not in ['Schedule:Compact','RunPeriod']]
            ph=digest(physical)
            if phys_hash is None:phys_hash=ph
            if ph!=phys_hash:errors.append('PHYSICAL_CORE_CHANGED')
            tanks=[values(r) for r in rows if r[0]=='WaterHeater:Stratified']
            configured='water_heater' in w['joint_matching']['types']
            if bool(tanks)!=configured:errors.append('TANK_PRESENCE')
            if tanks:
                t=tanks[0]
                for key,want in [('tank_volume',.12),('heater_1_capacity',3000),('maximum_temperature_limit',65),('uniform_skin_loss_coefficient_per_unit_area_to_ambient_temperature',1.2)]:
                    if abs(float(t[key])-want)>1e-9:errors.append('TANK_PARAMETER:'+key)
            coils=[values(r) for r in rows if r[0]=='Coil:Cooling:DX:SingleSpeed']
            acs=[d for d in w['parameter_pack']['devices'] if 'ac' in d['types']]
            if len(coils)!=len(acs):errors.append('AC_INSTANCE_COUNT')
            for c,d in zip(coils,acs):
                if abs(float(c['gross_rated_total_cooling_capacity'])-d['parameters']['cooling_W'])>1e-7:errors.append('AC_CAPACITY')
            counts['IDFs_read']+=1
        sa={r[1]:r for r in rowsA if r[0]=='Schedule:Compact'};sb={r[1]:r for r in rowsB if r[0]=='Schedule:Compact'}
        if sa.keys()!=sb.keys():errors.append('SCHEDULE_KEYS')
        date=__import__('datetime').date.fromisoformat(p['date']);start=date-__import__('datetime').timedelta(days=7)
        for name,a in sa.items():
            # Most occupancy/background schedules are byte-identical, so no expansion is needed.
            if a==sb[name]:continue
            for day in range(8):
                dat=start+__import__('datetime').timedelta(days=day);stop=p['decision_abs_min'] if day==7 else 1440
                for minute in range(0,stop,10):
                    if schedule_at(a,dat,minute)!=schedule_at(sb[name],dat,minute):errors.append('IDF_COMMON_PREFIX_CHANGED');break
        counts['pairs_read']+=1;counts['proposal:'+p['proposal']['family']]+=1
    counts['worlds_read']+=1;counts['K:'+str(w['joint_matching']['type_count'])]+=1
    return {'household_id':w['household_id'],'errors':sorted(set(errors)),'counts':dict(counts),'physical_core_sha256':phys_hash}
def main():
    school_guard();bs=read(OUT/'WORLD_BINDINGS1000.json')['records'];result=[];crashes=[]
    compiled={h['household_id']:h['records'] for h in read(OUT/'IDF_BINDINGS20000.json')['households']}
    for b in bs:b['compiled_records']=compiled[b['household_id']]
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
        fs={pool.submit(audit_one,b):b['household_id'] for b in bs}
        for f in concurrent.futures.as_completed(fs):
            try:result.append(f.result())
            except Exception as e:crashes.append({'household_id':fs[f],'error':str(e)})
    counts=collections.Counter()
    for r in result:counts.update(r['counts'])
    failures=[r for r in result if r['errors']]
    save(OUT/'WHOLE_COHORT_REVIEW.json',{'host':platform.node(),'counts':dict(counts),'failed_households':failures,'audit_crashes':crashes,
        'EP_started':0,'model_API_calls':0,'human_answers':0,'all_static_checks_pass':not failures and not crashes and len(result)==1000,
        'checks_scope':'saved artifact schema/value/reference checks,source anchors,all paired demand/resource/operator constraints,canonical physical core and actual-IDF common prefix',
        'not_proven':['EnergyPlus runtime success','delivered temperature/hot water','OEM offdesign calibration','national joint stock representativeness','human behavioral validity']})
    print({'counts':dict(counts),'failed':len(failures),'crashes':len(crashes)},flush=True)
    if failures or crashes:raise RuntimeError(str((failures[:2],crashes[:2])))
if __name__=='__main__':main()
