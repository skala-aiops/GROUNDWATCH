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
    from backend.groundwater_service import GroundwaterService
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
        extension_dir = source.parent if (source.parent/'seoul_observation_extension_manifest.json').exists() else None
        generated, generated_manifest = build_extension(source, manifest, service.root/'current-extension',
                                                        observed_extension_dir=extension_dir)
        content, mapping = generated.read_bytes(), generated_manifest.read_bytes()
        dataset_id = hashlib.sha256(content+mapping).hexdigest()
        try:
            entry = service.store.get('dataset', dataset_id)
            print(f'[GroundWatch] 과제용 합성 확장 자료: {entry["status"]}', flush=True)
        except KeyError:
            service.queue_upload(content, mapping, generated.name, auto_train=True)
            print('[GroundWatch] 오늘까지 합성 확장 자료를 별도 검증·학습합니다.', flush=True)
        import json
        stamp = json.loads((generated.parent/'generation.json').read_text())
        entry = service.store.get('dataset', dataset_id)
        entry['generated_at'] = stamp['generated_at']
        service.store.put('dataset', entry, dataset_id)
    children = [subprocess.Popen([sys.executable, '-m', 'backend.groundwater_worker']),
                subprocess.Popen([sys.executable, '-m', 'backend.external_worker']),
                subprocess.Popen([sys.executable, '-m', 'backend.national_worker']),
                subprocess.Popen([sys.executable, '-m', 'backend.weather_worker']),
                subprocess.Popen([sys.executable, '-m', 'backend.national_observation_worker']),
                subprocess.Popen([sys.executable, 'scripts/evaluate_national_seasons.py', '--worker']),
                subprocess.Popen([sys.executable, 'scripts/evaluate_national_seasons.py', '--worker', '--source-kind', 'synthetic',
                                  '--max-epochs', os.getenv('GROUNDWATCH_SIMULATION_TRAIN_EPOCHS', '10')]),
                subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.main:app',
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
