"""Bound TensorFlow worker lifetime and serialize heavy work across processes."""
import argparse
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


@contextmanager
def tensorflow_worker_lock(state_root):
    root=Path(state_root);root.mkdir(parents=True,exist_ok=True)
    with (root/'tensorflow-worker.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def run_isolated(command, *, store=None, stop_requested=lambda:False, shutdown_timeout=15):
    """A child owns exactly one unit. Abnormal exits retain interrupted jobs."""
    environment=os.environ.copy()
    for key in ('TF_NUM_INTRAOP_THREADS','TF_NUM_INTEROP_THREADS','OMP_NUM_THREADS'):
        environment.setdefault(key,'1')
    child=subprocess.Popen(command,env=environment,start_new_session=True)
    while child.poll() is None:
        if stop_requested():
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:child.wait(timeout=shutdown_timeout)
            except subprocess.TimeoutExpired:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait()
            break
        time.sleep(.1)
    code=child.returncode
    if code and store is not None:
        store.recover()  # Running -> interrupted, never queued/retried.
    return code


def has_queued_jobs(store):
    # jobs() intentionally limits UI history to 100; workers must see the queue.
    with store.connect() as db:
        return db.execute("SELECT 1 FROM jobs WHERE status='queued' LIMIT 1").fetchone() is not None


def has_pending_jobs(store):
    with store.connect() as db:
        return db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') LIMIT 1").fetchone() is not None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',default=os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
    parser.add_argument('--action',choices=('groundwater-job','groundwater-reconcile','national-job','national-schedule','external-cycle'))
    parser.add_argument('--locked-command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    with tensorflow_worker_lock(args.state_root):
        if args.locked_command:
            command=args.locked_command
            if command[0]=='--':command=command[1:]
            return subprocess.call(command)
        if args.action=='external-cycle':
            from serving_app.external_observations import ExternalObservations
            from serving_app.groundwater_service import GroundwaterService
            from serving_app.live_observations import LiveObservations
            from serving_app.groundwater_store import now
            external=ExternalObservations(args.state_root)
            scheduled=external.schedule_due()
            result=LiveObservations(GroundwaterService(args.state_root)).cycle()
            external.store.put('worker',{'checked_at':now(),'schedule':scheduled,'cycle_status':result['status']},'external')
        elif args.action and args.action.startswith('national-'):
            from serving_app.national_service import NationalService
            service=NationalService(args.state_root)
            service.execute_one() if args.action=='national-job' else service.schedule_once()
        else:
            from serving_app.groundwater_service import GroundwaterService
            service=GroundwaterService(args.state_root)
            if args.action=='groundwater-job':service.execute_one()
            elif args.action=='groundwater-reconcile':
                for folder in (service.root/'models').glob('*'):
                    if folder.is_dir() and list(folder.glob('*.json')):service.manager(folder.name).reconcile()
            else:parser.error('action or locked-command required')
    return 0


if __name__=='__main__':raise SystemExit(main())
