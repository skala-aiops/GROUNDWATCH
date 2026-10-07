"""Isolated UI verification server; NEVER used by the product Compose service.

python3 tests/frontend_fixture.py --port 8111
Uses the test gateway and a temporary database. No production model metrics.
"""
import argparse
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import uvicorn
from serving_app.backend.api import create_backend_app
from serving_app.backend.core import Settings
from serving_app.backend.service import BackendService
from test_backend import StubGateway


class SlowTestGateway(StubGateway):
    def predict(self, model, sequence):
        time.sleep(0.08)
        return super().predict(model, sequence)

    def retrain(self, model, rows, policy, emit):
        result = super().retrain(model, rows, policy, emit)
        candidate = replace(result.candidate, registry_version=str(int(model.registry_version) + 1))
        if result.promoted:
            self.info = candidate
        return replace(result, candidate=candidate)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8111)
    parser.add_argument('--failure-marker', type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix='groundwatch-ui-test-') as temp:
        settings = Settings(db_path=Path(temp)/'test.db', rmse_threshold_cm=1,
                            gate_threshold_cm=2, auto_retrain=True, policy_version='test-only')
        service = BackendService(settings, SlowTestGateway(error=3))
        api = create_backend_app(service)
        app = FastAPI()
        app.mount('/api/v1', api)
        app.router.add_event_handler('startup', service.start)
        app.router.add_event_handler('shutdown', service.close)
        app.mount('/', StaticFiles(directory=Path(__file__).resolve().parents[1]/'serving_app/static', html=True))
        @app.middleware('http')
        async def deliberate_failure(request, call_next):
            if args.failure_marker and args.failure_marker.exists() and request.url.path.startswith('/api/v1'):
                return JSONResponse(status_code=503, content={'error': {'code': 'TEST_UNAVAILABLE', 'message': '테스트용 서버 연결 실패', 'details': []}, 'meta': {'request_id': 'test-only'}})
            return await call_next(request)
        uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
