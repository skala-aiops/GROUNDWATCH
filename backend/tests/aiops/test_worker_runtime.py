"""Real subprocess checks for serialization, lifetime and interrupted history."""
import json
import os
from pathlib import Path
import subprocess
import sys

from backend.groundwater_store import Store
from backend.worker_runtime import run_isolated,has_queued_jobs,has_pending_jobs


def test_heavy_processes_share_one_file_lock(tmp_path):
    events=tmp_path/'events.jsonl'
    script="""import json,sys,time
with open(sys.argv[1],'a') as f:f.write(json.dumps([sys.argv[2],'start'])+'\\n')
time.sleep(.15)
with open(sys.argv[1],'a') as f:f.write(json.dumps([sys.argv[2],'end'])+'\\n')
"""
    base=[sys.executable,'-m','backend.worker_runtime','--state-root',str(tmp_path),
          '--locked-command',sys.executable,'-c',script,str(events)]
    children=[subprocess.Popen(base+[name]) for name in ('first','second')]
    for child in children:assert child.wait(timeout=10)==0
    entries=[json.loads(line) for line in events.read_text().splitlines()]
    assert entries[0][0]==entries[1][0]
    assert entries[2][0]==entries[3][0]
    assert [item[1] for item in entries]==['start','end','start','end']


def test_each_unit_has_a_fresh_process(tmp_path):
    pids=[]
    for i in range(2):
        output=tmp_path/str(i)
        assert run_isolated([sys.executable,'-c','import os,sys;open(sys.argv[1],"w").write(str(os.getpid()))',str(output)])==0
        pids.append(int(output.read_text()))
    assert len(set(pids))==2 and os.getpid() not in pids


def test_child_crash_preserves_failed_and_interrupted_jobs_without_retry(tmp_path):
    db=tmp_path/'jobs.sqlite3';store=Store(db)
    failed=store.enqueue('test',{},'old-failed');store.finish(failed['id'],error='original failure')
    running=store.enqueue('test',{},'interrupted')
    waiting=store.enqueue('test',{},'waiting')
    script='import os,sys;from backend.groundwater_store import Store;Store(sys.argv[1]).claim();os._exit(9)'
    assert run_isolated([sys.executable,'-c',script,str(db)],store=store)==9
    assert store.job(running['id'])['status']=='interrupted'
    assert store.job(waiting['id'])['status']=='queued'
    assert store.job(failed['id'])['error']=='original failure'
    assert len(store.jobs())==3


def test_shutdown_terminates_child_and_marks_only_running_work_interrupted(tmp_path):
    store=Store(tmp_path/'jobs.sqlite3');job=store.enqueue('test',{},'test')
    ready=tmp_path/'ready'
    script='import sys,time;from backend.groundwater_store import Store;Store(sys.argv[1]).claim();open(sys.argv[2],"w").write("ready");time.sleep(30)'
    code=run_isolated([sys.executable,'-c',script,str(store.path),str(ready)],store=store,stop_requested=ready.exists,shutdown_timeout=1)
    assert code!=0
    assert store.job(job['id'])['status']=='interrupted'


def test_queue_checks_are_not_limited_by_ui_history(tmp_path):
    store=Store(tmp_path/'jobs.sqlite3')
    old=store.enqueue('test',{},'old')
    for i in range(102):
        completed=store.enqueue('test',{},'finished-'+str(i));store.finish(completed['id'],result={})
    assert len(store.jobs())==100
    assert has_queued_jobs(store) and has_pending_jobs(store)
    assert store.claim()['id']==old['id']
    assert not has_queued_jobs(store) and has_pending_jobs(store)
    store.finish(old['id'],result={})
    assert not has_pending_jobs(store)
