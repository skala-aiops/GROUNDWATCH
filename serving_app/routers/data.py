"""샘플 CSV 검증·업로드·현재 데이터 상태 조회."""
import csv
import io
import os
import time
import math
from datetime import date

from fastapi import APIRouter, File, HTTPException, UploadFile

from data.features import SEQ_LEN, load_rows
from data.storage import UPLOAD_DIR, latest_upload
from serving_app.monitoring.drift_detector import WINDOW_SIZE

router = APIRouter(prefix="/data")

REQUIRED_COLUMNS = {"Date", "Close", "Volume"}
MIN_ROWS = SEQ_LEN + WINDOW_SIZE

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "UTF-8로 인코딩된 CSV 파일만 업로드할 수 있습니다.")

    reader = csv.DictReader(io.StringIO(text))
    if not REQUIRED_COLUMNS.issubset(set(reader.fieldnames or [])):
        raise HTTPException(400, f"CSV에 {sorted(REQUIRED_COLUMNS)} 컬럼이 모두 있어야 합니다.")
    rows = list(reader)
    if len(rows) < MIN_ROWS:
        raise HTTPException(400, f"최소 {MIN_ROWS}행 이상의 데이터가 필요합니다.")

    previous_date = None
    try:
        for row in rows:
            day = date.fromisoformat(row["Date"])
            close, volume = float(row["Close"]), float(row["Volume"])
            if not math.isfinite(close) or close <= 0 or not math.isfinite(volume) or volume < 0:
                raise ValueError("종가는 유한한 양수, 거래량은 유한한 0 이상 값이어야 합니다.")
            if previous_date is not None and day <= previous_date:
                raise ValueError("날짜는 중복 없이 과거에서 최근 순서여야 합니다.")
            previous_date = day
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, f"CSV 데이터가 올바르지 않습니다: {exc}") from exc

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    dest = os.path.join(UPLOAD_DIR, f"haic_{time.time_ns()}.csv")
    with open(dest, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    return {"filename": os.path.basename(dest), "rows": len(rows)}

@router.get("/status")
def status():
    try:
        path = latest_upload()
    except FileNotFoundError:
        return {"exists": False}

    rows = load_rows(path)
    closes = [r["Close"] for r in rows]
    return {
        "exists": True,
        "filename": os.path.basename(path),
        "rows": len(rows),
        "start_date": rows[0]["Date"],
        "end_date": rows[-1]["Date"],
        "min_close": min(closes),
        "max_close": max(closes),
    }
