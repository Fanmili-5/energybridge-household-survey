"""Engineering QA view of source floor polygons, not a publication figure."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as Patch
from shapely.geometry import Polygon

out=Path(__file__).resolve().parent.parent
fig,axes=plt.subplots(2,2,figsize=(15,10))
colors={3:'#bfdbfe',4:'#fed7aa',30:'#fed7aa',5:'#bbf7d0',6:'#ddd6fe',17:'#e5e7eb',31:'#fef08a',32:'#fef08a'}
labels={3:'L',4:'M',30:'B',5:'K',6:'T',17:'?',31:'S',32:'S'}
for ax,key in zip(axes.flat,['HighT','HighS','Low','Th']):
 x=json.loads((out/f'{key}_Beijing_2018_NATIVE.json').read_text())
 floor=x['rooms'][0]['floor_id'];rs=[r for r in x['rooms'] if r['floor_id']==floor]
 for r in rs:
  co=r['floor_xy_polygon_m'];shape=Polygon(co);p=shape.representative_point()
  ax.add_patch(Patch(co,facecolor=colors.get(r['source_function_code'],'white'),edgecolor='#334155',linewidth=.7))
  ax.text(p.x,p.y,labels.get(r['source_function_code'],'?'),ha='center',va='center',fontsize=7)
 xs=[a for r in rs for a,b in r['floor_xy_polygon_m']];ys=[b for r in rs for a,b in r['floor_xy_polygon_m']]
 xmin,ymin=min(xs),min(ys);height=max(ys)-ymin;bar_y=ymin-height*.10
 ax.plot([xmin,xmin+5],[bar_y,bar_y],color='#334155',linewidth=2)
 ax.text(xmin+2.5,bar_y-height*.035,'5 m',ha='center',va='top',fontsize=8)
 ax.autoscale_view();ax.set_aspect('equal');ax.set_axis_off()
 ax.set_title(f'{key} Beijing 2018 | native modeled floor 0',fontsize=12)
fig.suptitle('Source floor geometry and room functions retained',fontsize=19,y=.985)
fig.text(.5,.05,'L: living space | M: main bedroom | B: bedroom | S: study | K: kitchen | T: bathroom | ?: source type 17',ha='center',fontsize=11)
fig.text(.5,.023,'Door access and census gross-area bridge remain unknown. Apartment groups are inferred, not official dwelling IDs.',ha='center',fontsize=10)
fig.tight_layout(rect=(.02,.08,.98,.95));fig.savefig(out/'NATIVE_LAYOUTS_QA.png',dpi=170);plt.close(fig)
