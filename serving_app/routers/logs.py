"""AIOps 로그 목록과 내용 조회."""
import os

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/logs")

LOG_DIR = "logs"

@router.get("")
def list_logs():
    if not os.path.isdir(LOG_DIR):
        return []
    files = []
    for name in sorted(os.listdir(LOG_DIR)):
        path = os.path.join(LOG_DIR, name)
        if os.path.isfile(path):
            files.append({"name": name, "size": os.path.getsize(path)})
    return files

@router.get("/{filename}")
def read_log(filename: str):

    if filename != os.path.basename(filename):
        raise HTTPException(status_code=400, detail="잘못된 파일명입니다")

    path = os.path.join(LOG_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="로그 파일을 찾을 수 없습니다")

    with open(path, encoding="utf-8") as f:
        content = f.read()
    return {"name": filename, "content": content}
