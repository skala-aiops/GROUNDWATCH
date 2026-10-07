"""기존 FastAPI 서버 아래 /api/v1에 연결할 웹 API."""
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Literal
from uuid import UUID
import logging

from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.concurrency import run_in_threadpool

from .core import APIError, uid
from .schemas import (AnalysisRequest, Check, Dashboard, Dataset, Envelope, ErrorEnvelope, Event,
                      Forecast, ForecastRequest, Kind, Mode, Run, Well, Observation)
from .service import BackendService, page

log = logging.getLogger(__name__)


def allow_query(*keys):
    def validate(request: Request):
        pairs = request.query_params.multi_items()
        if any(key not in keys for key, _ in pairs) or len(pairs) != len(set(key for key, _ in pairs)):
            raise APIError(422, "INVALID_DATA", "지원하지 않거나 중복된 query 항목입니다.")
    return Depends(validate)


def pagination(limit: Annotated[int, Query(ge=1, le=100)] = 50,
               cursor: Annotated[str | None, Query(max_length=2048)] = None):
    return limit, cursor


def create_backend_app(service=None):
    service = service or BackendService()

    @asynccontextmanager
    async def lifespan(app):
        service.start()
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="GroundWatch Web API", version="0.1.0", lifespan=lifespan,
                  description="관측소별 지하수위 예측·평가 API. 서울 25개 구의 연구용 후보 모델을 지원합니다. HAIC 모델은 지하수 예측으로 사용하지 않습니다.")
    app.state.service = service

    def error(request, status, code, message, details=None):
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or []},
                            "meta": {"request_id": request.state.request_id}})

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_id = uid()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("GroundWatch API failure request_id=%s", request.state.request_id)
            response = error(request, 500, "INTERNAL_ERROR", "요청을 처리하지 못했습니다.")
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(APIError)
    async def domain_error(request, exc):
        return error(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        malformed = any(e["type"] == "json_invalid" for e in exc.errors())
        return error(request, 400 if malformed else 422, "MALFORMED_REQUEST" if malformed else "INVALID_DATA",
                     "요청 형식과 필수 값을 확인하세요.", [{"field": ".".join(map(str, e["loc"])), "reason": e["type"]} for e in exc.errors()])

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, "NOT_FOUND" if exc.status_code == 404 else "MALFORMED_REQUEST", "요청 주소와 형식을 확인하세요.")

    errors = {code: {"model": ErrorEnvelope} for code in (400, 404, 409, 413, 415, 422, 500, 503)}
    router = APIRouter(responses=errors)

    def envelope(request, value):
        return {"data": value, "meta": {"request_id": request.state.request_id}}

    def listing(request, values, limits):
        scope = {"path": request.url.path, "query": sorted((k, v) for k, v in request.query_params.items() if k not in ("limit", "cursor"))}
        data, cursor = page(values, scope, *limits)
        return {"data": data, "meta": {"request_id": request.state.request_id, "next_cursor": cursor}}

    @router.get("/wells", response_model=Envelope[list[Well]], dependencies=[allow_query("limit", "cursor")])
    def wells(request: Request, limits=Depends(pagination)):
        return listing(request, service.wells(), limits)

    @router.get("/model-reports", response_model=Envelope[list[dict]], dependencies=[allow_query("limit", "cursor")])
    def model_reports(request: Request, limits=Depends(pagination)):
        gateway = service.gateway
        stations = getattr(gateway, "stations", {})
        values = [dict(gateway.report(key), id=key) for key in stations]
        values.sort(key=lambda value: value["district"])
        return listing(request, values, limits)

    @router.get("/wells/{well_id}/model-report", response_model=Envelope[dict | None], dependencies=[allow_query()])
    def model_report(well_id: UUID, request: Request):
        service.datasets(str(well_id))  # Existing not-found semantics.
        report = getattr(service.gateway, "report", None)
        return envelope(request, report(str(well_id)) if callable(report) else None)

    @router.get("/wells/{well_id}/datasets", response_model=Envelope[list[Dataset]], dependencies=[allow_query("limit", "cursor")])
    def datasets(well_id: UUID, request: Request, limits=Depends(pagination)):
        return listing(request, service.datasets(str(well_id)), limits)

    @router.post("/wells/{well_id}/datasets", status_code=201, response_model=Envelope[Dataset],
                 responses={200: {"model": Envelope[Dataset]}}, dependencies=[allow_query()])
    async def upload(well_id: UUID, request: Request, response: Response, file: Annotated[UploadFile, File()],
                     source_kind: Annotated[Literal["simulated", "measured"], Form()],
                     scenario: Annotated[Literal["baseline", "drift"] | None, Form()] = None,
                     parent_dataset_id: Annotated[UUID | None, Form()] = None):
        try:
            form = await request.form()
            if set(form.keys()) - {"file", "source_kind", "scenario", "parent_dataset_id"} or len(form.multi_items()) != len(form):
                raise APIError(422, "INVALID_DATA", "지원하지 않거나 중복된 form 항목입니다.")
            if not (file.filename or "").lower().endswith(".csv") or file.content_type not in ("text/csv", "application/csv", "application/octet-stream", "text/plain"):
                raise APIError(415, "UNSUPPORTED_MEDIA_TYPE", "CSV 파일을 선택하세요.")
            raw = await file.read(service.settings.max_upload_bytes + 1)
            result, created = await run_in_threadpool(service.upload, str(well_id), raw, file.filename or "upload.csv", source_kind, scenario,
                                                      str(parent_dataset_id) if parent_dataset_id else None)
            response.status_code = 201 if created else 200
            return envelope(request, result)
        finally:
            await file.close()

    @router.get("/datasets/{dataset_id}", response_model=Envelope[Dataset], dependencies=[allow_query()])
    def dataset(dataset_id: UUID, request: Request):
        return envelope(request, service.dataset(str(dataset_id)))

    @router.get("/wells/{well_id}/observations", response_model=Envelope[list[Observation]], dependencies=[allow_query("dataset_id", "from", "to", "limit", "cursor")])
    def observations(well_id: UUID, dataset_id: UUID, request: Request,
                     start: Annotated[date | None, Query(alias="from")] = None,
                     end: Annotated[date | None, Query(alias="to")] = None, limits=Depends(pagination)):
        values = service.observations(str(well_id), str(dataset_id), start.isoformat() if start else None, end.isoformat() if end else None)
        return listing(request, values, limits)

    @router.get("/wells/{well_id}/dashboard", response_model=Envelope[Dashboard], dependencies=[allow_query("dataset_id", "mode")])
    def dashboard(well_id: UUID, dataset_id: UUID, request: Request, mode: Mode = "live"):
        return envelope(request, service.dashboard(str(well_id), str(dataset_id), mode))

    @router.post("/wells/{well_id}/forecasts", status_code=201, response_model=Envelope[Forecast],
                 responses={200: {"model": Envelope[Forecast]}}, dependencies=[allow_query()])
    def predict(well_id: UUID, body: ForecastRequest, request: Request, response: Response,
                key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        value, created = service.predict(str(well_id), str(body.dataset_id), body.input_end_date.isoformat(), str(key))
        response.status_code = 201 if created else 200
        return envelope(request, value)

    @router.get("/wells/{well_id}/forecasts", response_model=Envelope[list[Forecast]],
                dependencies=[allow_query("dataset_id", "mode", "model_version_id", "from", "to", "limit", "cursor")])
    def forecasts(well_id: UUID, dataset_id: UUID, request: Request, mode: Mode = "live", model_version_id: UUID | None = None,
                  start: Annotated[date | None, Query(alias="from")] = None,
                  end: Annotated[date | None, Query(alias="to")] = None, limits=Depends(pagination)):
        values = service.forecasts(str(well_id), str(dataset_id), mode, start.isoformat() if start else None,
                                   end.isoformat() if end else None, str(model_version_id) if model_version_id else None)
        return listing(request, values, limits)

    @router.get("/checks/{check_id}", response_model=Envelope[Check], dependencies=[allow_query()])
    def check(check_id: UUID, request: Request):
        return envelope(request, service.check(str(check_id)))

    @router.post("/wells/{well_id}/analyses", status_code=202, response_model=Envelope[Run], dependencies=[allow_query()])
    def analyse(well_id: UUID, body: AnalysisRequest, request: Request, response: Response,
                key: Annotated[UUID, Header(alias="Idempotency-Key")]):
        result = service.analyse(str(well_id), str(body.dataset_id), body.from_date.isoformat(), body.to_date.isoformat(), str(key))
        response.headers["Location"] = "/api/v1/runs/" + result["id"]
        return envelope(request, result)

    @router.get("/wells/{well_id}/runs", response_model=Envelope[list[Run]], dependencies=[allow_query("dataset_id", "kind", "limit", "cursor")])
    def runs(well_id: UUID, dataset_id: UUID, request: Request, kind: Kind | None = None, limits=Depends(pagination)):
        return listing(request, service.runs(str(well_id), str(dataset_id), kind), limits)

    @router.get("/runs/{run_id}", response_model=Envelope[Run], dependencies=[allow_query()])
    def run(run_id: UUID, request: Request):
        return envelope(request, service.run(str(run_id)))

    @router.get("/runs/{run_id}/events", response_model=Envelope[list[Event]], dependencies=[allow_query("limit", "cursor")])
    def events(run_id: UUID, request: Request, limits=Depends(pagination)):
        return listing(request, service.events(str(run_id)), limits)

    app.include_router(router)
    return app


def install_backend(app: FastAPI):
    """Mounted subapps do not receive lifespan events from their parent."""
    backend = create_backend_app()
    app.mount("/api/v1", backend)
    app.router.add_event_handler("startup", backend.state.service.start)
    app.router.add_event_handler("shutdown", backend.state.service.close)
