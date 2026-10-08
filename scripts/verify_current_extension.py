"""Actual HTTP verification of labelled current-date coursework forecasts."""
import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

base = sys.argv[1] if len(sys.argv)>1 else 'http://localhost:8099'
out = Path(sys.argv[2]) if len(sys.argv)>2 else Path('/tmp/current-extension-http.json')


def get(path):
    with urllib.request.urlopen(base+'/api/v1'+path,timeout=90) as response:
        assert response.status == 200
        return json.load(response)


today = datetime.now(ZoneInfo('Asia/Seoul')).date()
forecast = get('/forecasts?mode=current')
assert forecast['as_of']==str(today) and forecast['ready_count']==25
assert not forecast['simulation']['enabled']
assert forecast['provenance']['kind']=='observed_plus_synthetic_extension'
assert all(r['source_kind']=='synthetic' and r['input_origin']=='synthetic'
           and r['forecast_date']==str(today+timedelta(days=1)) and r['prediction'] is not None
           for r in forecast['forecasts'])
history = get('/districts/11110/history')
assert history['history'][-1]['date']==str(today+timedelta(days=1))
assert history['history'][-1]['groundwater_level'] is None
assert history['history'][-2]['origin']=='synthetic'
models=get('/models')
assert len(models['models'])==25
assert all(r['namespace'].startswith('synthetic_') for r in models['models'])
datasets=get('/datasets')['datasets']
observed=next(r for r in datasets if r['source_kind']=='observed' and r['status']=='ready')
original=get('/forecasts?as_of=2024-03-18&dataset_id='+observed['id'])
assert original['ready_count']==25
assert all(r['source_kind']=='observed' for r in original['forecasts'])
jobs=get('/jobs')['jobs']
training=next(r for r in jobs if r['kind']=='train' and r.get('result',{}).get('requested_count')==25)
assert training['status']=='completed' and len(training['result']['models'])==25
assert all(r['gate_passed'] for r in training['result']['models'])
result={'passed':True,'purpose':'Labelled synthetic coursework extension; not real Seoul current observation accuracy',
        'verified_at':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
        'forecast':forecast,'history':history,'models':models,'training':training,
        'original_observed_ready_count':original['ready_count'],
        'datasets':datasets}
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':True,'ready_count':25,'as_of':str(today),
                  'forecast_date':str(today+timedelta(days=1)),
                  'historical_ready_count':original['ready_count'],'output':str(out)},ensure_ascii=False))
