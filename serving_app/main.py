"""GroundWatch 도메인 API와 정적 대시보드."""
import asyncio
import contextlib
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from serving_app.groundwater_api import router_for
from serving_app.groundwater_service import GroundwaterService

logging.basicConfig(level=logging.INFO)
logging.getLogger("groundwatch.http").setLevel(logging.INFO)

def create_app(service=None, national_service=None):
    instance = service or GroundwaterService()
    @asynccontextmanager
    async def lifespan(app):
        async def collect():
            while True:
                await asyncio.sleep(60)
                try:
                    await asyncio.to_thread(instance.evaluate_service_health)
                except Exception:
                    logging.exception('service metrics evaluation failed')
        task = asyncio.create_task(collect())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    app = FastAPI(lifespan=lifespan,title="GroundWatch", version="1.0.0", description="관측소별 지하수위 예측과 전국 관측 자료·모델 품질 감시")
    app.state.service = instance
    @app.middleware('http')
    async def observe(request: Request, call_next):
        started, request_id, status = time.perf_counter(), uuid.uuid4().hex, 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers['X-Request-ID'] = request_id
            return response
        finally:
            if request.url.path.startswith('/api/v1/') and 'metrics/summary' not in request.url.path:
                route = getattr(request.scope.get('route'),'path','unmatched')
                latency = time.perf_counter()-started
                try:
                    await asyncio.to_thread(instance.store.request_metric,request.method,route,status,latency,request_id)
                except Exception:
                    logging.exception('request metric persistence failed')
                logging.getLogger('groundwatch.http').info(json.dumps({'request_id':request_id,'method':request.method,
                    'route':route,'status':status,'latency_seconds':round(latency,6)}))

    @app.exception_handler(KeyError)
    async def missing(request: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        status = 409 if "이미 대기" in str(exc) or "초기화가 완료" in str(exc) else 422
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    app.include_router(router_for(app.state.service))
    from serving_app.national_service import NationalService
    from serving_app.national_api import router_for as national_router
    app.state.national = national_service or NationalService(instance.root)
    app.include_router(national_router(app.state.national))
    from serving_app.network_service import NetworkService
    from serving_app.network_api import router_for as network_router
    app.state.network = NetworkService(instance, app.state.national)
    app.include_router(network_router(app.state.network))
    static = str(Path(__file__).parent / "static")
    app.mount("/static", StaticFiles(directory=static), name="assets")
    # Preserve the original dashboard while serving the React production build.
    dashboard = Path(__file__).parent / "dashboard"
    if (dashboard / "index.html").exists():
        @app.get("/", include_in_schema=False)
        async def dashboard_entry(request: Request):
            query = "?" + request.url.query if request.url.query else ""
            return RedirectResponse("/dashboard/" + query)
        app.mount("/dashboard", StaticFiles(directory=str(dashboard), html=True), name="dashboard")
    app.mount("/legacy", StaticFiles(directory=static, html=True), name="legacy-dashboard")
    app.mount("/", StaticFiles(directory=static, html=True), name="fallback-dashboard")
    return app

app = create_app()
