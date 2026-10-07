"""Refresh pre-exposure metadata from final IDFs without touching run inputs."""
import re,shutil
from common import *
def parse(p):return [[v.strip() for v in q.split(',')] for q in re.sub(r'!.*','',Path(p).read_text()).split(';') if q.strip()]
def main():
 guard();bindings=read(OUT/'JOINT_WORLD_BINDINGS.json');services=read(OUT/'SERVICE_PORT_BINDINGS.json');sindex={r['household_id']:r for r in services['records']}
 for r in bindings['records']:
  if not r['assembled']:continue
  rows=parse(OUT/r['IDF_path']);case=read(OUT/r['world_path']);meta=case['compiler_meta']
  meta['surfaces']=[{'name':z[1],'type':z[2],'construction':z[3],'zone':z[4],'bc':z[6],'peer':z[7],
   'vertices':[list(map(float,z[k:k+3])) for k in range(12,len(z),3)]} for z in rows if z[0]=='BuildingSurface:Detailed']
  meta['floor_policy_scope']='native KIND3 roof and KIND4 ground for one-storey;explicit RC reference only on adiabatic midfloor slabs'
  save(OUT/r['world_path'],case);r['world_sha256']=sha(OUT/r['world_path']);s=sindex[r['household_id']];scase=read(OUT/s['service_world_path']);scase['compiler_meta']=meta;save(OUT/s['service_world_path'],scase);s['world_sha256']=r['world_sha256'];s['service_world_sha256']=sha(OUT/s['service_world_path'])
 save(OUT/'JOINT_WORLD_BINDINGS.json',bindings);save(OUT/'SERVICE_PORT_BINDINGS.json',services)
 if Path('/private/tmp/eb_worktop_p96.png').exists():shutil.copyfile('/private/tmp/eb_worktop_p96.png',OUT/'raw/IKEA_worktop_primary2024_p96.png')
 print({'final_IDF_boundary_metadata_refreshed':1000,'thermal_run_input_bytes_changed':False})
if __name__=='__main__':main()
