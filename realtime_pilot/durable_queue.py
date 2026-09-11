"""Bounded execution over a persisted queue; no per-submission executor futures."""
import threading
import logging
import sqlite3

class DurableQueue:
    def __init__(self,store,workers):
        self.store=store
        self.workers=workers
        self.active=set()
        self.stopped=False
        self.wake=threading.Event()
        self.thread=None

    def submit(self,*unused):
        self.resume()

    def resume(self):
        with self.store.lock:
            if self.stopped:return
            if self.thread is None or not self.thread.is_alive():
                self.thread=threading.Thread(target=self.loop,daemon=True,name='durable-dispatcher')
                self.thread.start()
        self.wake.set()

    def loop(self):
        while not self.stopped:
            delay=.25
            try:
                with self.store.lock:
                    if not self.stopped:
                        self.store.expire_queued()
                        pending=sorted((j for j in self.store.jobs.summaries() if j['status']=='queued' and j['id'] not in self.active),key=lambda j:(j['created_at'],j['id']))
                        for job in pending[:max(0,self.workers-len(self.active))]:
                            self.active.add(job['id'])
                            threading.Thread(target=self.run,args=(job['id'],),daemon=True,name='job-'+job['id']).start()
            except (sqlite3.Error,OSError):
                logging.exception('Queue storage temporarily unavailable; will retry')
                delay=1
            self.wake.wait(delay)
            self.wake.clear()

    def run(self,jid):
        try:self.store.execute(jid)
        finally:
            with self.store.lock:self.active.discard(jid)
            self.wake.set()

    def shutdown(self,wait=True,cancel_futures=False):
        self.stopped=True
        self.wake.set()
        if self.thread:self.thread.join()
        if wait:
            while True:
                with self.store.lock:
                    if not self.active:break
                self.wake.wait(.05)
                self.wake.clear()
