"""Joint load/program/unload placement without invented helpers or spare chores."""
import bisect
from common import ANCHOR,dt,origin,overlap

class Scheduler:
    def __init__(self,w,days):
        self.w=w;self.days=days;self.ops=[];self.tasks=[];self.person_busy=set();self.room_busy=set()
        self.asset_busy={};self.cache={};self.room_blocks={}
        for key,d in days.items():
            base=origin(dt.date.fromisoformat(key));target=d['activity'];shared=d['shared']
            bath=w['activity_contract']['room_map']['bath']
            for t in target['family_context']['bath_times_min'].values():self.room_blocks.setdefault(bath,set()).add(base+t)
            for r in shared['facility_reservations']:
                for t in range(base+r['start_min'],base+r['end_min'],10):self.room_blocks.setdefault(r['room_id'],set()).add(t)

    def slots(self,lo,hi,room):
        key=(lo//1440,hi//1440,room)
        if key not in self.cache:
            result=[]
            for day in range(lo//1440,hi//1440+1):
                date=ANCHOR+dt.timedelta(days=day);data=self.days.get(str(date))
                if data is None:continue
                for oid,windows in data['activity']['operator_windows_min'].items():
                    for a,b in windows:
                        for t in range(day*1440+a,day*1440+b-9,10):
                            if t not in self.room_blocks.get(room,set()):result.append((t,oid))
            self.cache[key]=sorted(result)
        return [(t,o)for t,o in self.cache[key]if lo<=t and t+10<=hi and
                (o,t)not in self.person_busy and(room,t)not in self.room_busy]

    def op(self,slot,kind,nid,asset,room):
        t,oid=slot;self.person_busy.add((oid,t));self.room_busy.add((room,t))
        result={'operation_id':nid+':'+kind,'need_id':nid,'kind':kind,'operator_id':oid,
                'asset_id':asset,'room_id':room,'start_min':t,'end_min':t+10,'duration_min':10}
        self.ops.append(result);return result

    def appliance_free(self,asset,lo,hi):
        seq=self.asset_busy.get(asset,[]);position=bisect.bisect_left(seq,(lo,-1))
        return not(position and seq[position-1][1]>lo)and not(position<len(seq)and seq[position][0]<hi)

    def batch(self,device,nid,kind,release,deadline,preferred,dryer=False):
        asset=device['asset_id'];room=device['room_id'];duration=120+(90 if dryer else 0)if kind=='washer'else 90
        max_wait=240 if dryer else 90 if kind=='washer'else 720
        loads=self.slots(release,deadline-duration,room);unloads=self.slots(release+duration+10,deadline,room)
        if not loads or not unloads:raise ValueError('NO_EXPLICIT_BATCH_HANDLER:'+nid)
        lt=[s[0]for s in loads];ut=[s[0]for s in unloads];best=None
        for start in range(((release+19)//10)*10,deadline-duration,10):
            minute=start%1440
            if not 390<=minute or minute+duration>1410:continue
            # Machine remains occupied through retrieval, not just motor end.
            pos=bisect.bisect_right(lt,start-10)-1
            if pos<0:continue
            load=loads[pos]
            if start-(load[0]+10)>720:continue
            u=bisect.bisect_left(ut,start+duration)
            if u==len(unloads):continue
            unload=unloads[u]
            if unload[0]-(start+duration)>max_wait:continue
            if not self.appliance_free(asset,load[0],unload[0]+10):continue
            cost=abs(start-preferred)+.4*(start-load[0]-10)+.5*(unload[0]-start-duration)
            candidate=(cost,start,load,unload)
            if best is None or candidate<best:best=candidate
        if best is None:raise ValueError('NO_JOINT_LOAD_RUN_RETRIEVE:'+nid)
        _,start,load,unload=best
        self.op(load,'load',nid,asset,room);self.op(unload,'unload',nid,asset,room)
        bisect.insort(self.asset_busy.setdefault(asset,[]),(load[0],unload[0]+10))
        rows=[{'task_id':nid,'need_id':nid,'asset_id':asset,'kind':kind,'start_min':start,'end_min':start+(120 if kind=='washer'else 90)}]
        if dryer:rows.append({'task_id':nid+':dry','need_id':nid+':dry','upstream_need_id':nid,'asset_id':asset,'kind':'dryer','start_min':start+120,'end_min':start+210})
        self.tasks+=rows
        return rows,{'load_min':load[0],'unload_min':unload[0],'preload_wait_min':start-load[0]-10,
                     'retrieval_wait_min':unload[0]-start-duration,'maximum_retrieval_wait_min':max_wait,
                     'program_start_uses_given_timer':start>load[0]+10}

    def ev_operation(self,device,nid,kind,lo,hi,preferred):
        slots=self.slots(lo,hi,device['room_id'])
        if not slots:raise ValueError('NO_EXPLICIT_EV_HANDLER:'+nid+':'+kind)
        slot=min(slots,key=lambda x:(abs(x[0]-preferred),x))
        return self.op(slot,kind,nid,device['asset_id'],device['room_id'])
