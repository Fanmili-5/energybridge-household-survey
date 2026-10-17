"""Readable all1000 review table and actual source/new floorplan comparisons."""
import collections,csv,json,os
from common import *


def main():
    records=read(OUT/'WORLD_BINDINGS1000.json')['records'];folder=OUT/'review';folder.mkdir(exist_ok=True)
    rows=[];worlds={};originals={};source=BASE/'substantive_repair_v30_20261015'
    for r in records:
        hid=r['household_id'];w=read(OUT/r['world_path']);old=read(source/'worlds'/(hid+'.json'));worlds[hid]=w;originals[hid]=old
        f=w['layout']['stock_reference_features'];original=old['layout']['stock_reference_features']
        rows.append({'家庭ID':hid,'类别':r['type'],'省份':w['province'],'人数':w['N'],'代数':w['G'],'原面积㎡':old['H6'],'新面积㎡':w['H6'],
            '卧室数':w['H7'],'合住户数':w['layout']['shared_household_count_design'],'明确邻户人数':w['shared_context']['auxiliary_residents_count'],
            '设备类别数':len(r['classes']),'设备类别':','.join(r['classes']),'空调实例数':r['AC_units'],
            '床型':json.dumps(dict(collections.Counter(f['kind']for f in w['layout']['sleep_reference']['frames'])),ensure_ascii=False),
            '有非同住监护人':bool(w['background_context']['nonresident_guardian']),
            '原厨房':original['kitchen'],'新厨房':f['kitchen'],'原结构':original['load_bearing_structure'],'新结构':f['load_bearing_structure'],
            '原电梯':original['elevator'],'新电梯':f['elevator'],'原住房取得方式':original['housing_source'],'新住房取得方式':f['housing_source'],
            '原原型':old['layout']['source_parameter_reference']['model_key'],'新原型':w['layout']['source_parameter_reference']['model_key'],
            '布局语法':w['layout']['reference_grammar'],'围护场景':w['background_context']['envelope_reference']['mode'],
            '原世界SHA256':r['source_world_sha256'],'新世界SHA256':r['world_sha256'],'新世界文件':r['world_path']})
    path=folder/'家庭住房设备1000户核对表.csv'
    with path.open('w',encoding='utf-8-sig',newline='')as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    save(folder/'50户筛选清单.json',read(OUT/'SUBSET50.json'))
    os.environ.setdefault('MPLCONFIGDIR',str(folder/'.matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    for hid in['ordinary-v6-0001','ordinary-v6-0139','ordinary-v6-0031','ordinary-v6-0334','ordinary-v6-0661','ordinary-v6-0828']:
        fig,axes=plt.subplots(1,2,figsize=(14,6),layout='constrained')
        for ax,w,title in zip(axes,[originals[hid],worlds[hid]],['Source V30','Rebuilt master V33']):
            for room in w['layout']['rooms']:
                rid=room['room_id'];x0,y0,x1,y1=room['gross_rect_m'];users=room['using_household_ids']
                color='#d3eee6'if users==[hid]else'#e4edf7'if hid in users else'#eeeeee'
                ax.add_patch(Rectangle((x0,y0),x1-x0,y1-y0,facecolor=color,edgecolor='#7c8b91',lw=.8))
                ax.text((x0+x1)/2,(y0+y1)/2,rid.replace('private_','room ').replace('combined_bed_living','bed/living').replace('living_hall','living'),ha='center',va='center',fontsize=6,color='#3b4c54')
            for witness in w.get('joint_matching',{}).get('spatial_witnesses',[]):
                x0,y0,x1,y1=witness['body_rect_m'];ax.add_patch(Rectangle((x0,y0),x1-x0,y1-y0,facecolor='#a9c2ce',edgecolor='#566a70',alpha=.8,lw=.7))
            sleeps=[w['layout']['sleep_reference']]+[h['sleep_reference']for h in w.get('shared_context',{}).get('households',[])]
            for i,sleep in enumerate(sleeps):
                for bed in sleep['frames']:
                    x0,y0,x1,y1=bed['outer_rect_m'];ax.add_patch(Rectangle((x0,y0),x1-x0,y1-y0,facecolor='#228c72'if i==0 else'#c68b48',edgecolor='#244b43',lw=.8,alpha=.85))
                    ax.text((x0+x1)/2,(y0+y1)/2,{'single':'S','double':'D','bunk':'B','crib':'C'}.get(bed['kind'],'?'),ha='center',va='center',fontsize=6,color='white')
            ax.set_aspect('equal');ax.autoscale_view();ax.set_xlabel('m');ax.set_ylabel('m');ax.set_title(f'{title}\nN={w["N"]}, H6={w["H6"]} m2, H7={w["H7"]}, q={w["layout"]["shared_household_count_design"]}',fontsize=10);ax.grid(alpha=.12)
        fig.suptitle(hid+' | S single, D linked-couple double, B bunk, C crib; brown = explicit auxiliary beds',fontsize=10)
        plot=folder/'plots'/(hid+'.png');plot.parent.mkdir(exist_ok=True);fig.savefig(plot,dpi=160);plt.close(fig)
    summary={'households':len(rows),'residents':sum(w['N']for w in worlds.values()),'AC_households':sum(any('ac'in d['types']for d in w['parameter_pack']['devices'])for w in worlds.values()),
        'functional_class_distribution':dict(collections.Counter(len(r['classes'])for r in records)),
        'source_areas_retained':all(w['H6']==originals[hid]['H6']for hid,w in worlds.items()),
        'configured_housing_changes':dict(collections.Counter(c['field']for w in worlds.values()for c in w['housing_condition_changes'])),
        'guardian_supported_households':sum(bool(w['background_context']['nonresident_guardian'])for w in worlds.values()),
        'shared_context_households':sum(bool(w['shared_context']['households'])for w in worlds.values()),
        'explicit_auxiliary_residents':sum(w['shared_context']['auxiliary_residents_count']for w in worlds.values()),
        'envelope_reference_modes':dict(collections.Counter(w['background_context']['envelope_reference']['mode']for w in worlds.values())),
        'native_building_families':dict(collections.Counter(w['layout']['source_parameter_reference']['catalogue_type']for w in worlds.values())),
        'sample50_counts':read(OUT/'SUBSET50.json')['class_counts'],'table_path':str(path.relative_to(OUT)),
        'EP_started':0,'new_AB_or_questionnaire_released':False}
    save(OUT/'DELIVERY_SUMMARY.json',summary);print(canonical(summary))

if __name__=='__main__':main()
