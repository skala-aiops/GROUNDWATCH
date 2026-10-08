"""SQLite에서 작업을 원자적으로 가져오는 단일 학습 프로세스."""
import logging
import signal
import time
import sys
from backend.worker_runtime import run_isolated,has_queued_jobs
from backend.groundwater_service import GroundwaterService

def main():
    logging.basicConfig(level=logging.INFO)
    service = GroundwaterService()
    logging.info('GroundWatch worker: %d interrupted jobs', service.store.recover())
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    base=[sys.executable,'-m','backend.worker_runtime','--state-root',str(service.root),'--action']
    run_isolated(base+['groundwater-reconcile'],store=service.store,stop_requested=lambda:stopping)
    while not stopping:
        if has_queued_jobs(service.store):
            run_isolated(base+['groundwater-job'],store=service.store,stop_requested=lambda:stopping)
        else:
            time.sleep(.5)

if __name__ == '__main__':
    main()
