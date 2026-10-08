"""Reproduce an isolated synthetic training/promotion smoke, never Seoul performance.

Run inside the project environment: python scripts/verify_model_promotion.py
Every invocation creates a fresh run folder under --state-dir, never reuses or
updates the application's operational model namespaces. Results include every
attempt and use unchanged gates. Optional --verify-http needs httpx2/TestClient.
"""
import argparse
import json, math, random, traceback, os, sys, uuid
from datetime import datetime, timezone
from datetime import date,timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--state-dir',type=Path,default=Path(os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch')).parent/'promotion-smoke')
parser.add_argument('--verify-http',action='store_true',help='Also call isolated FastAPI TestClient; requires httpx2.')
args=parser.parse_args()
from backend.groundwater_models import ModelManager
root=args.state_dir.resolve()/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
root.mkdir(parents=True,exist_ok=True)
results={'run_root':str(root),'purpose':'synthetic actual-TensorFlow successful-promotion smoke; not observed Seoul performance','seed':42,'attempts':[]}
def rows(values,start=0):
    return [{'date':str(date(2020,1,1)+timedelta(days=start+i)),'groundwater_level':v,'rainfall_mm':float((start+i)%7), 'station_id':'synthetic-well','district_code':'11110','level_unit':'synthetic_level'} for i,v in enumerate(values)]
metadata={'station_id':'synthetic-well','district_code':'11110','level_unit':'synthetic_level','dataset_version':'synthetic-ar1-trend-v1','mapping_version':'synthetic-fixed-v1','manifest_approved':True,'source_kind':'synthetic','model_architecture':'residual_lstm','learning_rate':.0001}
rng=random.Random(42)
levels=[10.]
for i in range(1,410):
    levels.append(10.+.8*(levels[-1]-10.)+rng.gauss(0,.2))
base=ModelManager(root,namespace='initial')
initial=base.train('11110',rows(levels),metadata,max_epochs=30)
results['initial']=initial
(root/'results.json').write_text(json.dumps(results,indent=2))
if initial['status']=='promoted':
    for number,slope in enumerate((.02,.05,.1,.2,.4),1):
        attempt={'number':number,'slope':slope,'synthetic_rule':'After original410days, deterministic linearlevel change; candidate trains41days, shadow only next30 new actual labels.'}
        try:
            manager=ModelManager(root,namespace=f'trend_{number}')
            manager.clone_from(base,'11110',metadata)
            newlevels=[levels[-1]+slope*(i+1) for i in range(71)]
            observed=rows(newlevels[:41],410)
            candidate=manager.fine_tune('11110',observed,metadata)
            attempt['candidate']=candidate
            pending=manager.evaluate_candidate('11110',candidate['candidate_version'],rows(newlevels[:60],410))
            attempt['before30labels']=pending
            evaluation=manager.evaluate_candidate('11110',candidate['candidate_version'],rows(newlevels,410)[-50:])
            attempt['evaluation']=evaluation
            if evaluation['status']=='promoted':
                attempt['actual_prediction_after_promotion']=manager.predict('11110',rows(newlevels,410)[-20:])
                attempt['initial_prediction_same_input']=base.predict('11110',rows(newlevels,410)[-20:])
                if args.verify_http:
                    from fastapi.testclient import TestClient
                    from backend.groundwater_service import GroundwaterService
                    os.environ['GROUNDWATCH_STATE_DIR']=str(root/'http-module-state')
                    from backend.main import create_app
                    service=GroundwaterService(root/'http-service',manager_factory=lambda namespace:manager)
                    keys=('date','groundwater_level','rainfall_mm','station_id','level_unit')
                    sequence=[{k:r[k] for k in keys} for r in rows(newlevels,410)[-20:]]
                    with TestClient(create_app(service)) as client:
                        response=client.post('/api/v1/districts/11110/predict',json={'sequence':sequence})
                    attempt['isolated_http']={'status_code':response.status_code,'response':response.json()}
                    assert response.status_code==200 and response.json()['model_version']==evaluation['model_version']
        except Exception as error:
            attempt['error']=f'{type(error).__name__}: {error}'
            attempt['traceback']=traceback.format_exc()
        results['attempts'].append(attempt)
        (root/'results.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(attempt),flush=True)
        if attempt.get('evaluation',{}).get('status')=='promoted': break
print(json.dumps(results),flush=True)

raise SystemExit(0 if any(a.get('evaluation',{}).get('status')=='promoted' and not a.get('error') for a in results['attempts']) else 1)
