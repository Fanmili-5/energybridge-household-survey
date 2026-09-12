"""Reconnect private SSH paths via the user's already connected workstation.

cloud localhost:18768 -> workstation localhost:18769 -> school localhost:18768
school localhost:18080 -> workstation localhost:18081 (existing restricted API relay)
No request bodies or model secrets are handled by this supervisor.
"""
import argparse
import fcntl
import logging
import os
from pathlib import Path
import signal
import subprocess
import threading

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cloud',required=True);p.add_argument('--cloud-key',type=Path,required=True)
    p.add_argument('--cloud-known-hosts',type=Path,required=True)
    p.add_argument('--school',required=True);p.add_argument('--pid-file',type=Path,required=True)
    a=p.parse_args();os.umask(0o077)
    a.pid_file.parent.mkdir(parents=True,exist_ok=True)
    lock=a.pid_file.with_suffix('.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    common=['ssh','-N','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
            '-o','ConnectTimeout=8','-o','ExitOnForwardFailure=yes',
            '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2']
    commands={
        'school':common+['-L','127.0.0.1:18769:127.0.0.1:18768',
                          '-R','127.0.0.1:18080:127.0.0.1:18081',a.school],
        'cloud':common+['-i',str(a.cloud_key),'-o','UserKnownHostsFile='+str(a.cloud_known_hosts),
                         '-R','127.0.0.1:18768:127.0.0.1:18769',a.cloud],
    }
    def supervise(name,command):
        while not stop.is_set():
            logging.info('Connecting %s SSH route',name)
            child=subprocess.Popen(command,stdin=subprocess.DEVNULL)
            try:
                while child.poll() is None and not stop.wait(1):pass
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
            if not stop.is_set():logging.warning('%s route disconnected; reconnecting',name);stop.wait(5)
    a.pid_file.write_text(str(os.getpid()))
    threads=[threading.Thread(target=supervise,args=(k,v)) for k,v in commands.items()]
    try:
        for t in threads:t.start()
        for t in threads:t.join()
    finally:stop.set();a.pid_file.unlink(missing_ok=True)

if __name__=='__main__':main()
