"""학습 worker와 분리한 외부 관측 수집·일별 발행 worker. 검증 매핑만 사용합니다."""
import os
import signal
import time
from serving_app.groundwater_store import now
from serving_app.external_observations import ExternalObservations

def main():
    service=ExternalObservations(os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
    from serving_app.groundwater_service import GroundwaterService
    from serving_app.live_observations import LiveObservations
    live=LiveObservations(GroundwaterService(os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch')))
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
                scheduled=service.schedule_due()
                result=live.cycle()
                service.store.put('worker',{'checked_at':now(),'schedule':scheduled,'cycle_status':result['status']},'external')
            except Exception:
                service.store.put('worker',{'checked_at':now(),'status':'failed',
                    'reason':'수집/발행 주기 실패. 민감한 예외 원문은 노출하지 않습니다.'},'external')
            last_cycle=time.monotonic()
        if not service.execute_one():
            time.sleep(.5)

if __name__=='__main__':
    main()
