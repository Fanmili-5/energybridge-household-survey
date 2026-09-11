"""Start-time estimates, not promises; persisted deadlines bound actual queue waits."""
import heapq
import math


def forecast(rows, workers, now, cold_seconds, data_origin):
    rows=list(rows)
    # Real-participant timings must never be calibrated with fixed-planner tests.
    samples=sorted((r for r in rows if r.get('data_origin')==data_origin
                    and r.get('flow')=='paired_ep_v1'
                    and r.get('status') in {'complete','timeout'}
                    and r.get('started_at') is not None and r.get('finished_at') is not None
                    and r['finished_at']>r['started_at']),
                   key=lambda r:r['finished_at'])[-20:]
    durations=sorted(r['finished_at']-r['started_at'] for r in samples)
    estimate=max(1,durations[math.ceil(len(durations)*.8)-1]) if durations else cold_seconds
    basis='recent_runs' if durations else 'configured_cold_start'
    running=[r for r in rows if r.get('status')=='running']
    slots=[max(5,estimate-max(0,now-r.get('started_at',now))) for r in running]
    slots.extend([0]*max(0,workers-len(slots)))
    # Recovery can temporarily expose more running summaries than configured workers.
    slots=sorted(slots)[-workers:]
    heapq.heapify(slots)
    waiting=sorted((r for r in rows if r.get('status')=='queued'),key=lambda r:(r['created_at'],r['id']))
    waits={}
    for position,row in enumerate(waiting,1):
        start=heapq.heappop(slots)
        waits[row['id']]={'queue_position':position,'estimated_wait_seconds':math.ceil(start)}
        heapq.heappush(slots,start+estimate)
    return {'jobs':waits,'next_wait_seconds':math.ceil(slots[0]),'estimate_basis':basis}
