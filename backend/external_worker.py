"""학습 worker와 분리한 외부 관측 수집·일별 발행 worker. 검증 매핑만 사용합니다."""
import os
import signal
import time
import sys
from backend.worker_runtime import run_isolated
from backend.groundwater_store import now
from backend.external_observations import ExternalObservations

def main():
    service=ExternalObservations(os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
    service.store.recover()
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    last_cycle=0
    while not stopping:
        if time.monotonic()-last_cycle>=60:
            try:
                code=run_isolated([sys.executable,'-m','backend.worker_runtime','--state-root',os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'),'--action','external-cycle'],stop_requested=lambda:stopping)
                if code:raise RuntimeError('isolated cycle interrupted')
            except Exception:
                service.store.put('worker',{'checked_at':now(),'status':'failed',
                    'reason':'수집/발행 주기 실패. 민감한 예외 원문은 노출하지 않습니다.'},'external')
            last_cycle=time.monotonic()
        if not service.execute_one():
            time.sleep(.5)

if __name__=='__main__':
    main()
