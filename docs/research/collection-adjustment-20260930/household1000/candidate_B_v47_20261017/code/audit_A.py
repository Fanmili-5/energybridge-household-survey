"""Byte and family/hardware preservation audit of the rebuilt A46, not preservation of old calendars."""
from common import *
def main():
    records=read(A_STAGE/'A_BINDINGS10000.json')['records'];parent=BASE/'normal_A_v40_20261016';ps={r['household_id']:r for r in read(parent/'A_BINDINGS10000.json')['records']};bad=[];cases=0;days=0
    design=read(A_STAGE/'DESIGN_REVIEW.json')
    if not design['accepted']:raise ValueError('A_UPSTREAM_DESIGN_NOT_ACCEPTED')
    for r in records:
        old=ps[r['household_id']];w=read(A_STAGE/r['A_world_path']);ow=read(parent/old['A_world_path']);y=read(A_STAGE/r['annual_A_path']);problems=[];days+=len(y['days'])
        for key in('members','layout','parameter_pack','role_policy','random10_date_selection'):
            if w[key]!=ow[key]:problems.append('FAMILY_HARDWARE_OR_DATES_CHANGED:'+key)
        if r['HVAC_components_sha256']!=old['HVAC_components_sha256']:problems.append('HVAC_COMPONENTS_CHANGED')
        if not y.get('upstream_calendar_regenerated'):problems.append('OLD_ANNUAL_CALENDAR_REUSED')
        for pk,hk in [('A_world_path','A_world_sha256'),('annual_A_path','annual_A_sha256'),('HVAC_components_path','HVAC_components_sha256')]:
            if sha(A_STAGE/r[pk])!=r[hk]:problems.append('A_BYTES_CHANGED')
        for c in r['cases']:
            cases+=1
            if sha(A_STAGE/c['path'])!=c['sha256']:problems.append('CASE_CHANGED')
        if problems:bad.append({'household_id':r['household_id'],'errors':problems})
    accepted=not bad and cases==10000 and read(A_STAGE/'ACCEPTANCE.json')['accepted']
    save(OUT/'A_REAUDIT.json',{'accepted':accepted,'households':len(records),'cases':cases,'annual_days_compared':days,'failures':bad,'A_bindings_sha256':sha(A_STAGE/'A_BINDINGS10000.json'),'A_seal_sha256':sha(A_STAGE/'FINAL_SEAL.json'),'new_life_calendars_required':True,'family_hardware_and_dates_preserved':not bad,'whole_physical_acceptance':False})
    print({'accepted':accepted,'failures':bad[:5],'cases':cases})
    if not accepted:raise SystemExit(2)
if __name__=='__main__':main()
