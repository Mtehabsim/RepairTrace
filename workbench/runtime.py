"""Minimal user-namespace runtime for reproducible offline diagnostic agents."""
from pathlib import Path
import os
import signal
import subprocess
import time

HERE=Path(__file__).resolve().parent

def execute(repo,venv,evidence,root,command,timeout=120):
    repo,venv,evidence,root=map(lambda p:Path(p).resolve(),[repo,venv,evidence,root])
    prefix=(venv/'bin/python').resolve().parent.parent
    root.mkdir(parents=True,exist_ok=True)
    for p in ['usr','env','work','evidence','tmp','dev',str(prefix).lstrip('/')]:
        (root/p).mkdir(parents=True,exist_ok=True)
    for p in ['bin','lib','lib64']:
        target=root/p
        if not target.exists() and not target.is_symlink():
            if Path('/'+p).is_symlink():target.symlink_to(os.readlink('/'+p))
            else:target.mkdir()
    args=['unshare','--user','--map-root-user','--mount','--net','--pid','--fork',
          '/bin/bash',str(HERE/'sandbox_exec.sh'),str(root),str(repo),str(venv),str(prefix),str(evidence),command]
    start=time.monotonic()
    env={k:v for k,v in os.environ.items() if k not in {'BASH_ENV','ENV'}}
    proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True,env=env)
    timed_out=False
    try:out,_=proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out=True;os.killpg(proc.pid,signal.SIGKILL);out,_=proc.communicate()
    return {'exit_code':proc.returncode,'output':out,'seconds':time.monotonic()-start,'timed_out':timed_out}

