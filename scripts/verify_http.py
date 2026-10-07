"""실행 중인 API를 통해 실제 25개 예측·422·응답시간을 확인합니다."""
import argparse
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

def verify(base_url, as_of, count=100):
    path = base_url.rstrip('/') + '/api/v1/forecasts?as_of=' + as_of
    started = time.perf_counter()
    with urllib.request.urlopen(path, timeout=180) as response:
        forecasts = json.load(response)
    cold = time.perf_counter()-started
    assert len(forecasts['forecasts']) == forecasts['ready_count'] == 25, '25개 구 실제 모델 준비가 필요합니다.'
    assert all(isinstance(x['prediction'], (int,float)) and math.isfinite(x['prediction'])
               and x['model_version'] and x['source_kind'] == 'observed' for x in forecasts['forecasts'])
    samples, statuses = [], []
    for _ in range(count):
        begin = time.perf_counter()
        try:
            with urllib.request.urlopen(path, timeout=30) as response:
                body = json.load(response)
                statuses.append(response.status)
                assert body['ready_count'] == 25
        except urllib.error.HTTPError as exc:
            statuses.append(exc.code)
        samples.append(time.perf_counter()-begin)
    try:
        urllib.request.urlopen(base_url.rstrip('/')+'/api/v1/forecasts?as_of=2024-02-31')
        invalid = 200
    except urllib.error.HTTPError as exc:
        invalid = exc.code
    ordered = sorted(samples)
    p95 = ordered[max(0, math.ceil(.95*len(ordered))-1)]
    result = {'condition': 'single client, sequential repeated identical as_of after warmup; container-local HTTP if base URL localhost:8099',
        'as_of': as_of, 'requests': count, 'cold_seconds': cold, 'warm_p95_seconds': p95,
        'http_5xx_count': sum(status>=500 for status in statuses), 'statuses': {str(s):statuses.count(s) for s in set(statuses)},
        'invalid_date_status': invalid, 'forecasts': forecasts}
    assert invalid == 422
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://localhost:8099')
    parser.add_argument('--as-of', default='2024-03-17')
    parser.add_argument('--requests', type=int, default=100)
    parser.add_argument('--output', default='runtime/http-verification.json')
    args = parser.parse_args()
    if args.requests < 1:
        parser.error('--requests must be positive')
    result = verify(args.base_url, args.as_of, args.requests)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='forecasts'}, ensure_ascii=False))
