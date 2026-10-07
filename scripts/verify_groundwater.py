"""실제 HTTP로 25개 관측소의 추론·과거 재현·21건 오차 계산을 검증합니다."""
import argparse
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from uuid import uuid5, NAMESPACE_URL


def verify(base, output):
    def request(path, body=None):
        headers = {}
        if body is not None:
            headers = {'Content-Type': 'application/json', 'Idempotency-Key': str(uuid5(NAMESPACE_URL, path+json.dumps(body, sort_keys=True)))}
        req = Request(base+path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        with urlopen(req, timeout=90) as response:
            return json.load(response)['data']
    reports = request('/model-reports?limit=100')
    assert len(reports) == 25 and len({r['district'] for r in reports}) == 25
    results = []
    for report in reports:
        base_well = '/wells/'+report['well_id']
        datasets = request(base_well+'/datasets?limit=100')
        dataset = next(d for d in datasets if d['end_date'] == report['last_date'] and d['source_kind'] == 'measured')
        forecast = request(base_well+'/forecasts', {'dataset_id':dataset['id'], 'input_end_date':dataset['end_date']})
        assert forecast['model']['id'] == report['model_id']
        start = max(date.fromisoformat(dataset['start_date'])+timedelta(days=20), date.fromisoformat(report['evaluation_end_date'])+timedelta(days=1))
        run = request(base_well+'/analyses', {'dataset_id':dataset['id'], 'from':start.isoformat(), 'to':dataset['end_date'], 'mode':'replay'})
        deadline = time.monotonic()+120
        while run['status'] in ('queued','running') and time.monotonic() < deadline:
            time.sleep(.2)
            run = request('/runs/'+run['id'])
        assert run['status'] == 'succeeded', run
        check = request('/checks/'+run['result']['last_check_id'])
        assert check['sample_count'] == 21 and check['rmse_cm'] is not None, check
        assert check['state'] == 'not_evaluated', check  # No invented operational threshold.
        replay = request(base_well+'/forecasts?dataset_id='+dataset['id']+'&mode=replay&from='+start.isoformat()+'&to='+dataset['end_date']+'&limit=100')
        observations = request(base_well+'/observations?dataset_id='+dataset['id']+'&from='+start.isoformat()+'&to='+dataset['end_date']+'&limit=100')
        actual = {r['observed_date']:r['groundwater_depth_cm'] for r in observations}
        recent = sorted(replay,key=lambda r:r['target_date'])[-21:]
        rmse = (sum((actual[r['target_date']]-r['predicted_depth_cm'])**2 for r in recent)/21)**.5
        assert abs(rmse-check['rmse_cm']) < 1e-6
        result = dict(district=report['district'],station=report['station'],well_id=report['well_id'],dataset_id=dataset['id'],
                      input_end_date=dataset['end_date'],target_date=forecast['target_date'],predicted_depth_cm=forecast['predicted_depth_cm'],
                      recent_21_rmse_cm=check['rmse_cm'],replay_prediction_count=len(replay),model_id=report['model_id'],run_id=run['id'],status=run['status'])
        results.append(result)
        print(report['district'], 'OK', forecast['target_date'], round(forecast['predicted_depth_cm'],3), flush=True)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'http_verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'latest_forecasts.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(results[0]));writer.writeheader();writer.writerows(results)
    return results


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',default='http://127.0.0.1:8099/api/v1')
    parser.add_argument('--output',default='serving_app/models/groundwater/results')
    args=parser.parse_args()
    verify(args.base,args.output)
