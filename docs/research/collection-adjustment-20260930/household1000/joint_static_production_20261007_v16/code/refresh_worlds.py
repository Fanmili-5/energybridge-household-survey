"""Re-run the one constructor over saved selected geometry, without altering anchors."""
from common import *
from build_worlds import materialize
def main():
    school_guard();bs=read(OUT/'WORLD_BINDINGS1000.json');oldbs={b['household_id']:b for b in read(OLD/'WORLD_BINDINGS1000.json')['records']}
    priors={p['household_id']:p for p in read(OUT/'inputs/DEVICE_PRIOR_ROUTES1000.json')['routes']}
    for b in bs['records']:
        nw=read(OUT/b['world_path']);hid=b['household_id'];ob=oldbs[hid];w=read(OLD/ob['world_path'])
        c={'types':nw['joint_matching']['types'],'placements':nw['joint_matching']['spatial_witnesses'],
            'sleep_metric_access_witnesses':nw['joint_matching']['sleep_metric_access_witnesses']}
        nw=materialize(w,ob,c,priors[hid]);save(OUT/b['world_path'],nw)
        b.update(world_sha256=sha(OUT/b['world_path']),world_content_sha256=nw['world_content_sha256'],parameter_pack_sha256=nw['parameter_pack_sha256'])
    save(OUT/'WORLD_BINDINGS1000.json',bs);print({'constructor_replayed':len(bs['records'])},flush=True)
if __name__=='__main__':main()
