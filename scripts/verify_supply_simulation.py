"""Create one official-data supply demo and verify HTTP temporal boundaries."""
import json
import math
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:8099'
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('/tmp/supply-simulation-http.json')


def call(path, body=None, expected=200):
    request = Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=60) as response:
            status, value = response.status, json.load(response)
    except HTTPError as error:
        status, value = error.code, json.load(error)
    assert status == expected, (path, status, value)
    return value


def wait(job_id):
    for _ in range(240):
        job = call('/api/v1/jobs/' + job_id)
        if job['status'] in ('completed', 'failed', 'interrupted'):
            assert job['status'] == 'completed', job
            return job
        time.sleep(1)
    raise TimeoutError(job_id)


def main():
    defaults = call('/api/v1/pipeline')['defaults']
    today = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    request = {k: defaults[k] for k in ('dataset_id', 'start_date', 'end_date')}
    request.update(scenario='historical', presentation_start_date=today)
    replay = call('/api/v1/replays', request, 202)
    replay_id = replay['id']
    initial_job = wait(replay['job_id'])
    scope = '?replay_id=' + replay_id
    before = call('/api/v1/forecasts' + scope)
    assert before['ready_count'] == 25
    assert all(math.isfinite(row['prediction']) for row in before['forecasts'])
    assert before['simulation']['presentation_as_of'] == today
    assert before['as_of'] == defaults['start_date']
    first = before['forecasts'][0]
    history_before = call('/api/v1/districts/' + first['district_code'] + '/history' + scope)
    assert history_before['history'][-1]['groundwater_level'] is None
    assert history_before['history'][-1]['rainfall_mm'] is None
    assert history_before['history'][-1]['prediction'] is not None
    denied_future = call('/api/v1/forecasts' + scope + '&as_of=' + first['forecast_date'], expected=422)
    denied_batch = call('/api/v1/replays/' + replay_id + '/advance', {'days': 2}, 422)
    advance = call('/api/v1/replays/' + replay_id + '/advance', {'days': 1}, 202)
    advance_job = wait(advance['id'])
    after = call('/api/v1/forecasts' + scope)
    assert after['ready_count'] == 25
    assert after['as_of'] == first['forecast_date']
    assert after['simulation']['presentation_as_of'] == (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    history_after = call('/api/v1/districts/' + first['district_code'] + '/history' + scope)
    assert history_after['history'][-2]['groundwater_level'] is not None
    assert history_after['history'][-2]['prediction'] == first['prediction']
    assert history_after['history'][-1]['groundwater_level'] is None
    baseline = call('/api/v1/forecasts?as_of=2024-03-18')
    assert baseline['ready_count'] == 25 and not baseline['simulation']['enabled']
    result = {'purpose': 'Official historical values with simulated supply clock; not current real-world forecast',
              'passed': True, 'request': request, 'replay': replay, 'initial_job': initial_job,
              'before': before, 'history_before': history_before, 'denied_future': denied_future,
              'denied_batch': denied_batch, 'advance_job': advance_job, 'after': after,
              'history_after': history_after, 'baseline_ready_count': baseline['ready_count']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'passed': True, 'replay_id': replay_id, 'ready_count': after['ready_count'],
                      'before': before['simulation'], 'after': after['simulation'], 'output': str(OUT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
