"""API와 영속 학습 worker를 실행하고 종료 신호를 전달합니다."""
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    # Only the explicitly approved, bundled official data may bootstrap training.
    # A failed/interrupted job is retained and never silently retried on restart.
    import hashlib
    from serving_app.groundwater_service import GroundwaterService
    source = Path('data/groundwater_observations.csv')
    manifest = Path('data/representatives.json')
    if source.exists() and manifest.exists():
        service = GroundwaterService()
        contents, mapping = source.read_bytes(), manifest.read_bytes()
        dataset_id = hashlib.sha256(contents + mapping).hexdigest()
        try:
            entry = service.store.get('dataset', dataset_id)
            print(f'[GroundWatch] 저장된 공식 자료: {entry["status"]}', flush=True)
        except KeyError:
            service.queue_upload(contents, mapping, source.name, auto_train=True)
            print('[GroundWatch] 공식 자료 검증과 최초 25개 구 학습을 작업으로 등록했습니다.', flush=True)
    # Isolated coursework scenario: preserve official dataset/models and append
    # explicitly labelled synthetic rows only in a separate namespace.
    import os
    if source.exists() and manifest.exists() and os.getenv('GROUNDWATCH_CURRENT_EXTENSION', 'true').lower() == 'true':
        from data.current_extension import build_extension
        generated, generated_manifest = build_extension(source, manifest, service.root/'current-extension')
        content, mapping = generated.read_bytes(), generated_manifest.read_bytes()
        dataset_id = hashlib.sha256(content+mapping).hexdigest()
        try:
            entry = service.store.get('dataset', dataset_id)
            print(f'[GroundWatch] 과제용 합성 확장 자료: {entry["status"]}', flush=True)
        except KeyError:
            service.queue_upload(content, mapping, generated.name, auto_train=True)
            print('[GroundWatch] 오늘까지 합성 확장 자료를 별도 검증·학습합니다.', flush=True)
    children = [subprocess.Popen([sys.executable, '-m', 'serving_app.groundwater_worker']),
                subprocess.Popen([sys.executable, '-m', 'serving_app.external_worker']),
                subprocess.Popen([sys.executable, '-m', 'uvicorn', 'serving_app.main:app',
                                  '--host', '0.0.0.0', '--port', '8099', '--workers', '1'])]
    stopping = False
    requested_stop = False
    def stop(*_):
        nonlocal stopping, requested_stop
        requested_stop = True
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping and all(p.poll() is None for p in children):
            time.sleep(.3)
    finally:
        unexpected = not requested_stop
        stop()
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    if unexpected:
        return next((p.returncode if p.returncode > 0 else 128-p.returncode for p in children if p.returncode), 1)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
