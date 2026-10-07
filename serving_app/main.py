"""샘플 API·대시보드·AIOps 로그를 등록하는 서버 진입점."""
import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from serving_app import model_loader
from serving_app.backend.api import install_backend
from serving_app.routers import data, health, logs, predict

_LOG_DIR = "logs"
os.makedirs(_LOG_DIR, exist_ok=True)
_aiops_logger = logging.getLogger("aiops")
_aiops_logger.setLevel(logging.INFO)
if not _aiops_logger.handlers:
    _handler = logging.FileHandler(os.path.join(_LOG_DIR, "aiops.log"), encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _aiops_logger.addHandler(_handler)
    _aiops_logger.addHandler(logging.StreamHandler())

app = FastAPI(title="GroundWatch Development Baseline (HAIC sample)")

app.include_router(predict.router)
app.include_router(health.router)
app.include_router(data.router)
app.include_router(logs.router)

# Register the web API before the existing catch-all static mount.
install_backend(app)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")

@app.on_event("startup")
def startup():

    if os.getenv("LOADING_MODE", "lazy") == "eager":
        model_loader.load_eager()
    else:
        print("[lazy] 모델은 첫 /predict 요청이 들어올 때 로드됩니다.")
