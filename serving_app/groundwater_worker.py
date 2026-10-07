"""SQLite에서 작업을 원자적으로 가져오는 단일 학습 프로세스."""
import logging
import signal
import time
from serving_app.groundwater_service import GroundwaterService

def main():
    logging.basicConfig(level=logging.INFO)
    service = GroundwaterService()
    logging.info('GroundWatch worker: %d interrupted jobs', service.store.recover())
    for folder in (service.root/'models').glob('*'):
        if folder.is_dir() and list(folder.glob('*.json')):
            repaired = service.manager(folder.name).reconcile()
            if repaired:
                logging.warning('registry/local history recovered: %s %s',folder.name,repaired)
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        if not service.execute_one():
            time.sleep(.5)

if __name__ == '__main__':
    main()
