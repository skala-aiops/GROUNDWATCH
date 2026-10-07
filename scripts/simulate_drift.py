"""샘플 서버에 정상·변화 배치를 보내는 선택적 검증 도구."""
import argparse
import os
import sys

import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.features import load_rows
from data.storage import latest_upload

TARGETS = {
    "local": "http://localhost:8077",
    "container": os.getenv("CONTAINER_API_URL", "http://localhost:8100"),
}
API_URL = f"{TARGETS['local']}/predict/batch-test"

SAMPLE_CSV = "data/sample_haic_prices.csv"

def compute_baseline_stats(csv_path: str | None = None) -> tuple[float, float]:

    if csv_path is None:
        try:
            csv_path = latest_upload()
        except FileNotFoundError:
            csv_path = SAMPLE_CSV
            print(f"[info] 업로드된 CSV가 없어 {SAMPLE_CSV} 로 기준 통계를 계산합니다.")
    rows = load_rows(csv_path)
    closes = np.array([r["Close"] for r in rows])
    return float(closes.mean()), float(closes.std())

BATCH_N = 41

NORMAL_SIGMA = 0.012
DRIFT_SIGMA = NORMAL_SIGMA * 3

def _random_walk(n: int, base: float, sigma: float) -> np.ndarray:
    log_returns = np.random.normal(0, sigma, n)
    return base * np.exp(np.cumsum(log_returns))

def generate_normal_batch(n=BATCH_N, base=165.0, sigma=NORMAL_SIGMA):

    return _random_walk(n, base, sigma)

def generate_drift_batch(n=BATCH_N, base=165.0, sigma=DRIFT_SIGMA):

    return _random_walk(n, base, sigma)

def send_batch(prices: np.ndarray, label: str) -> dict:

    resp = requests.post(API_URL, json={"prices": prices.tolist()})
    resp.raise_for_status()
    result = resp.json()
    print(f"[{label}] drift_check = {result['drift_check']}")
    return result

def _summary(check: dict) -> str:
    if check.get("status") != "retrain_triggered":
        return check.get("status", "?")
    return f"retrain_triggered (promoted={check.get('promoted')}, rmse={check.get('rmse', 0):.2f})"

def main():
    global API_URL
    parser = argparse.ArgumentParser(description="HAIC 드리프트 감지 시뮬레이션")
    parser.add_argument("--target", choices=["local", "container", "both"], default="local",
                        help="local=8077, container=8100, both=같은 배치를 두 서버에 보내 비교")
    args = parser.parse_args()
    targets = ["local", "container"] if args.target == "both" else [args.target]

    mean, std = compute_baseline_stats()
    print(f"[1] 기준 통계: mean={mean:.2f}, std={std:.2f}")

    normal_batch = generate_normal_batch(base=mean)
    drift_batch = generate_drift_batch(base=mean)

    results = {}
    for name in targets:
        API_URL = f"{TARGETS[name]}/predict/batch-test"
        print(f"\n=== {name} ({TARGETS[name]}) ===")
        try:
            print("[2] 정상 입력 테스트 전송...")
            normal = send_batch(normal_batch, label=f"{name}/normal")
            print("[3-4] 드리프트 입력 주입...")
            drift = send_batch(drift_batch, label=f"{name}/drift_injection")
            results[name] = (normal["drift_check"], drift["drift_check"])
        except requests.exceptions.ConnectionError:
            print(f"[skip] {TARGETS[name]} 에 연결할 수 없습니다. 서버가 떠 있는지(/health) 확인하세요.")
            results[name] = None

    if len(targets) == 2:
        print("\n[비교] 같은 배치 → 서버별 결과")
        for name in targets:
            r = results[name]
            line = "연결 실패" if r is None else f"normal={_summary(r[0])} | drift={_summary(r[1])}"
            print(f"  {name:<9}: {line}")

    print("\n[5] 결과 확인: 각 대시보드의 재학습 로그(" + ", ".join(f"{TARGETS[n]}/" for n in targets)
          + ") 또는 서버 콘솔에서 [WARN] drift detected 로그를 확인하세요.")

if __name__ == "__main__":
    main()
