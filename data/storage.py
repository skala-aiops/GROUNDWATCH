"""가장 최근에 업로드한 CSV 경로를 찾습니다."""
import glob
import os

UPLOAD_DIR = "data/uploads"

def latest_upload(upload_dir: str = UPLOAD_DIR) -> str:

    files = sorted(glob.glob(os.path.join(upload_dir, "*.csv")), key=os.path.getmtime)
    if not files:
        raise FileNotFoundError(
            "업로드된 HAIC 데이터가 없습니다. 대시보드에서 CSV 파일을 먼저 업로드하세요 "
            f"(data/sample_haic_prices.csv를 예시로 업로드해볼 수 있습니다 -> {upload_dir}/)."
        )
    return files[-1]
