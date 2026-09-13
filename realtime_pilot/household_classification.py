"""Versioned, outcome-blind grouped Gower distance and deterministic PAM."""
import json
import math
from pathlib import Path
import argparse
import sqlite3
import numpy as np

VERSION='eb.household_facts_gower_pam.v1'
FACT_IDS=('B02','B04','F_EVENING','F_REGULARITY','F_LATE_USE','B05',
          'H_ac','H_ac_temp','H_washer','H_dishwasher','H_dryer','H_electric_water_heater','H_home_ev')
SPEC={'version':VERSION,'input_question_ids':list(FACT_IDS),
      'groups':{'household':['B02','B04','F_EVENING','F_REGULARITY','F_LATE_USE'],
                'inventory':['B05'],'habits':[q for q in FACT_IDS if q.startswith('H_')]},
      'weighting':'equal available-group weights; equal valid fields within each group; omit habit group when no jointly owned device',
      'distance':'Gower: normalized ordered/numeric differences, nominal mismatch; inventory Jaccard; task hours cyclic /12',
      'excluded':['all A_EB_* attitudes','task deadlines','decision','four scores','reason','EP outputs','VPP event'],
      'missing':'pairwise omission within groups; require household, inventory and habit evidence when equipment is owned',
      'selection':'PAM k=2..min(6,n//5); minimum 5 members; maximize mean silhouette among stable candidates',
      'stability':'20 subsamples (80 percent, no replacement), refit fixed k and compare full-data assignments with adjusted Rand; median >=0.75',
      'minimum_unique_households':30,'human_identity':'browser-session proxy; participant deduplication needed before scientific fitting',
      'release_status':'exploratory_method_not_validated_household_taxonomy'}

def feature_record(profile):
    features={k:(profile.get(k) or {}).get('value') if (profile.get(k) or {}).get('response_status')=='answered' else None for k in FACT_IDS}
    owned=features['B05']
    # Stale conditional values must never change class after ownership is removed.
    for k in FACT_IDS:
        if k.startswith('H_') and k[2:].replace('ac_temp','ac') not in (owned or []): features[k]=None
    return {'status':'not_fitted','household_type':None,'method_version':VERSION,'features':features,
            'input_question_ids':list(FACT_IDS),'uses_attitudes':False,'uses_decisions':False}

def field_distance(key,a,b):
    if key=='B05':
        sa,sb=set(a)-{'none'},set(b)-{'none'}
        return 1-len(sa&sb)/len(sa|sb) if sa|sb else 0.
    if key=='B02': return abs((6 if a=='6_plus' else int(a))-(6 if b=='6_plus' else int(b)))/5
    if key=='H_ac_temp': return abs(float(a)-float(b))/10
    ranks={'F_REGULARITY':['regular','partly_regular','irregular'],'F_LATE_USE':['rarely','sometimes','often']}
    if key in ranks:return abs(ranks[key].index(a)-ranks[key].index(b))/(len(ranks[key])-1)
    hours={'morning':8,'noon':12,'evening':18,'night':20,'late':22}
    if key.startswith('H_') and key!='H_ac':
        from survey_time import start_hour
        try:
            delta=abs(start_hour(a)-start_hour(b));return min(delta,24-delta)/12
        except (ValueError,TypeError):pass
    return float(a!=b)

def distance(a,b):
    groups=[]
    for name,keys in SPEC['groups'].items():
        ds=[field_distance(k,a[k],b[k]) for k in keys if a.get(k) is not None and b.get(k) is not None]
        if ds: groups.append(sum(ds)/len(ds))
        elif name=='habits' and a.get('B05')==b.get('B05')==['none']: groups.append(0.)
        elif name!='habits': raise ValueError('家庭规模和设备信息不足以计算距离')
    return sum(groups)/len(groups)

def pam(D,k):
    medoids=[int(D.sum(axis=1).argmin())]
    while len(medoids)<k:
        costs=[(np.minimum(D[:,medoids].min(axis=1),D[:,i]).sum(),i) for i in range(len(D)) if i not in medoids]
        medoids.append(min(costs)[1])
    while True:
        best=(D[:,medoids].min(axis=1).sum(),medoids)
        for m in range(k):
            for i in range(len(D)):
                if i in medoids:continue
                trial=medoids.copy();trial[m]=i; cost=D[:,trial].min(axis=1).sum()
                if cost<best[0]-1e-10:best=(cost,trial)
        if best[1]==medoids:break
        medoids=best[1]
    return medoids,np.argmin(D[:,medoids],axis=1)

def silhouette(D,labels):
    scores=[]
    for i in range(len(D)):
        own=np.flatnonzero(labels==labels[i]);own=own[own!=i]
        if not len(own):scores.append(0.);continue
        a=D[i,own].mean();b=min(D[i,labels==g].mean() for g in set(labels) if g!=labels[i])
        scores.append((b-a)/max(a,b) if max(a,b)>0 else 0.)
    return float(np.mean(scores))

def ari(a,b):
    choose=lambda n:n*(n-1)/2
    cells={};ca={};cb={}
    for x,y in zip(a,b):cells[x,y]=cells.get((x,y),0)+1;ca[x]=ca.get(x,0)+1;cb[y]=cb.get(y,0)+1
    s=sum(choose(n) for n in cells.values());x=sum(choose(n) for n in ca.values());y=sum(choose(n) for n in cb.values())
    expected=x*y/choose(len(a));denom=(x+y)/2-expected
    return float((s-expected)/denom) if denom else 1.

def fit(records,seed=20260910):
    if len(records)<SPEC['minimum_unique_households']:return {'status':'insufficient_households','n':len(records),'method':SPEC}
    if len({r['household_id'] for r in records})!=len(records):raise ValueError('Fit requires one frozen fact row per household')
    fs=[r['features'] for r in records];D=np.array([[distance(a,b) for b in fs] for a in fs]);trials=[];models={}
    for k in range(2,min(6,len(records)//5)+1):
        medoids,labels=pam(D,k);counts=np.bincount(labels,minlength=k)
        if min(counts)<5:continue
        scores=[];rng=np.random.default_rng(seed)
        for _ in range(20):
            indices=np.sort(rng.choice(len(D),int(.8*len(D)),replace=False));sub,_=pam(D[np.ix_(indices,indices)],k)
            assigned=np.argmin(D[:,indices[sub]],axis=1);scores.append(ari(labels,assigned))
        stability=float(np.median(scores));s=silhouette(D,labels)
        trials.append({'k':k,'silhouette':s,'stability_median_ari':stability,'counts':counts.tolist()});models[k]=(medoids,labels)
    eligible=[t for t in trials if t['stability_median_ari']>=.75 and t['silhouette']>0]
    if not eligible:return {'status':'no_stable_partition','n':len(records),'method':SPEC,'trials':trials}
    best=max(eligible,key=lambda t:(t['silhouette'],-t['k']));medoids,labels=models[best['k']]
    return {'status':'exploratory_fit','method':SPEC,'n':len(records),'seed':seed,'trials':trials,'selected':best,
            'medoids':[records[i] for i in medoids],
            'assignments':{r['household_id']:int(label) for r,label in zip(records,labels)}}

def intake_records(data_dir):
    """Return one outcome-blind feature row per human intake household."""
    database=Path(data_dir)/'state.sqlite3'
    if not database.is_file():raise FileNotFoundError('Classification requires authoritative state.sqlite3 intake records')
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        rows=[json.loads(row[0]) for row in db.execute('SELECT payload FROM household_submissions ORDER BY created,id')]
    unique={};conflicts=set()
    for intake in rows:
        if intake.get('data_origin')!='local_pilot_self_reported_human':continue
        hid=intake['household_id'];facts=feature_record(intake['profile'])['features']
        if hid in unique and unique[hid]['features']!=facts:conflicts.add(hid)
        unique.setdefault(hid,{'household_id':hid,'features':facts})
    return [row for hid,row in unique.items() if hid not in conflicts],sorted(conflicts)

def main():
    from common import ROOT,write_json
    parser=argparse.ArgumentParser(description='Exploratory outcome-blind clustering from authoritative intake receipts')
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data/web')
    parser.add_argument('--output',type=Path,default=ROOT/'exports/household_classification.json')
    args=parser.parse_args()
    records,conflicts=intake_records(args.data_dir)
    result=fit(records);result['excluded_conflicting_households']=sorted(conflicts)
    result['source']='authoritative_sqlite_household_submissions_all_human_intakes'
    result['includes_saved_without_generation']=True
    write_json(args.output,result)
    print(json.dumps({'status':result['status'],'n':len(records),'conflicts':len(conflicts)}))
if __name__=='__main__':main()
