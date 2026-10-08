"""Frozen chronological seasonal experiment. Never emits prospective predictions."""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serving_app.national_models import NationalModelManager, _score
from serving_app.national_service import NationalService


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.replace(temporary, path)


def chronological_split(rows):
    selected = [r for r in rows if '2026-01-01' <= r['date'] <= '2026-10-07']
    if len(selected) != 280 or selected[0]['date'] != '2026-01-01' or selected[-1]['date'] != '2026-10-07':
        raise ValueError('complete 280-day experimental source required')
    from datetime import date, timedelta
    if any(date.fromisoformat(b['date'])-date.fromisoformat(a['date']) != timedelta(days=1) for a,b in zip(selected, selected[1:])):
        raise ValueError('consecutive observations required')
    return selected, {'train_start':'2026-01-21','train_end':'2026-05-31','train_targets':131,
        'validation_start':'2026-06-01','validation_end':'2026-06-30','validation_targets':30,
        'holdout_start':'2026-07-01','holdout_end':'2026-10-07','holdout_targets':99,
        'context_days':20,'scaler_fit_end':'2026-05-31','scaler_fit_scope':'train_only'}


def persistence_metrics(rows, labels, threshold):
    actual = [r['groundwater_level'] for r in rows[20:]]
    predicted = [r['groundwater_level'] for r in rows[19:-1]]
    result={'metrics':_score(actual,predicted),'groups':{}}
    for group in ('rainy','non_rainy','heavy_rain'):
        indices=[j for j,r in enumerate(rows[20:]) if
            (r['rainfall_mm'] >= threshold and r['rainfall_mm'] > 0 if group=='heavy_rain'
             else group in labels.get(r['date'],[]))]
        result['groups'][group]=_score([actual[i] for i in indices],[predicted[i] for i in indices]) if indices else {'count':0,'rmse':None,'mae':None}
    return result


def _run(service, state_root, max_epochs=30, manager_factory=NationalModelManager):
    root=Path(state_root); report_path=root/'seasonal_evaluation.json'
    code_hash=_hash({name:hashlib.sha256((Path(__file__).resolve().parents[1]/name).read_bytes()).hexdigest()
        for name in ('serving_app/national_models.py','scripts/evaluate_national_seasons.py')})
    report=json.loads(report_path.read_text()) if report_path.exists() else {}
    if report.get('model_code_sha256') != code_hash or report.get('max_epochs') != max_epochs:
        report={'schema_version':1,'evaluation_mode':'retrospective','operational_promotion_evidence':False,
            'status':'running','model_code_sha256':code_hash,'max_epochs':max_epochs,'stations':[],
            'limitations':['과거 관측의 시간 분리 평가이며 실제 발행 예측·미래 30일 승격 증거가 아닙니다.',
                '소수 관측소·단일 연도 결과로 전국·모든 연도의 우수성을 주장하지 않습니다.']}
    station_entries={s['station_id']:s for s in report['stations']}
    stations=[]; cursor=None
    while True:
        page=service.repo.list_stations(cursor=cursor,limit=200)
        stations.extend(s for s in page['items'] if s.get('source_contract_verified') and s.get('mapping_status')=='experimental')
        cursor=page.get('next_cursor')
        if not cursor: break
    for station in stations:
        station_id=station['station_id']
        try:
            rows,split=chronological_split(service.repo.observations(station_id))
            source_hash=_hash({'station':station,'rows':rows})
            labels=service.seasonal_labels(station_id,rows)
            entry=station_entries.get(station_id)
            if not entry or entry.get('source_sha256')!=source_hash:
                entry={'station_id':station_id,'name':station['name'],'source_sha256':source_hash,
                    'split':split,'source_contract_verified':True,'operational_approved':False,
                    'weather_source_station_id':station.get('weather_source_station_id'),
                    'rainy_region':station.get('rainy_region'),'variants':{},'status':'running'}
                station_entries[station_id]=entry
            if entry.get('status')=='failed' and entry.get('source_sha256')==source_hash:
                continue
            experiment=_hash({'source':source_hash,'code':code_hash,'epochs':max_epochs})
            manager=manager_factory(root/'seasonal-evaluations'/experiment)
            guard=rows[161:]  # June 11--30 context; July 1 is first held-out target.
            for variant in ('M0','M1'):
                if entry['variants'].get(variant,{}).get('status')=='completed': continue
                trained=manager.train(station_id,rows,metadata=station,variant=variant,
                    validation_targets=30,holdout_targets=99,max_epochs=max_epochs)
                version=trained['version']
                if trained['scaler']['fit_through']!='2026-05-31' or trained['holdout_start']!='2026-07-01':
                    raise ValueError('frozen split invariant failed')
                evaluated=manager.evaluate(station_id,version,guard,seasonal_labels=labels)
                baseline=persistence_metrics(guard,labels,trained['heavy_rain_threshold_mm'])
                comparisons={}
                for group in ('overall','rainy','non_rainy','heavy_rain'):
                    metric=evaluated['metrics'] if group=='overall' else evaluated['groups'][group]
                    reference=baseline['metrics'] if group=='overall' else baseline['groups'][group]
                    denominator=reference['rmse']
                    comparisons[group]={'model':metric,'persistence':reference,
                        'rmse_reduction_ratio':(1-metric['rmse']/denominator) if denominator and metric['rmse'] is not None else None,
                        'zero_baseline_error':denominator==0}
                entry['variants'][variant]={'status':'completed','model_version':version,
                    'initial_gate_status':trained['status'],'feature_contract_id':trained['feature_contract_id'],
                    'heavy_rain_threshold_mm':trained['heavy_rain_threshold_mm'],
                    'heavy_rain_threshold_scope':'train_only_p95','evaluation':evaluated,
                    'comparisons':comparisons,'completed_at':datetime.now(timezone.utc).isoformat()}
                report.update(stations=list(station_entries.values()),updated_at=datetime.now(timezone.utc).isoformat())
                _atomic(report_path,report)
            entry['m1_vs_m0']={}
            for group in ('overall','rainy','non_rainy','heavy_rain'):
                old=entry['variants']['M0']['comparisons'][group]['model']
                new=entry['variants']['M1']['comparisons'][group]['model']
                entry['m1_vs_m0'][group]={'m0':old,'m1':new,
                    'rmse_reduction_ratio':1-new['rmse']/old['rmse'] if old['rmse'] and new['rmse'] is not None else None,
                    'minimum_30_targets_met':new['count']>=30}
            entry['status']='completed';entry.pop('error',None)
        except Exception as exc:
            entry=station_entries.setdefault(station_id,{'station_id':station_id,'name':station['name'],'variants':{}})
            entry.update(status='failed',error=f'{type(exc).__name__}: 계절 평가 실패. 자료·모델 준비 확인 필요')
        report.update(stations=list(station_entries.values()),updated_at=datetime.now(timezone.utc).isoformat())
        _atomic(report_path,report)
    report['status']='completed' if stations and all(e['status']=='completed' for e in report['stations']) else 'partial' if stations else 'data_required'
    _atomic(report_path,report)
    return report


def run(service,state_root,max_epochs=30,manager_factory=NationalModelManager):
    # One experiment writer across startup, manual container checks and restarts.
    import fcntl
    root=Path(state_root);root.mkdir(parents=True,exist_ok=True)
    with (root/'seasonal_evaluation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _run(service,state_root,max_epochs,manager_factory)


def worker(state_root,max_epochs):
    import signal
    import threading
    stopping=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopping.set())
    signal.signal(signal.SIGINT,lambda *_:stopping.set())
    enabled=os.getenv('GROUNDWATCH_SEASONAL_EVALUATION_ENABLED','false').lower() in ('1','true','yes')
    service=NationalService(state_root)
    while not stopping.is_set():
        if not enabled:
            stopping.wait(30)
            continue
        page=service.repo.list_stations(limit=200)
        stations=[s for s in page['items'] if s.get('source_contract_verified') and s.get('mapping_status')=='experimental']
        # Bootstrap's ordinary model jobs take precedence over this isolated experiment.
        busy=any(j['status'] in ('queued','running') for j in service.store.jobs())
        complete=len(stations)>=3 and all(len(service.repo.observations(s['station_id']))>=280 for s in stations)
        if busy or not complete:
            stopping.wait(5)
            continue
        run(service,state_root,max_epochs)
        stopping.wait(30)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',default=os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
    parser.add_argument('--max-epochs',type=int,default=int(os.getenv('GROUNDWATCH_SEASONAL_EVALUATION_EPOCHS','30')))
    parser.add_argument('--worker',action='store_true')
    args=parser.parse_args()
    if args.worker:
        worker(args.state_root,args.max_epochs)
        return
    report=run(NationalService(args.state_root),args.state_root,args.max_epochs)
    print(json.dumps({'status':report['status'],'stations':[{k:s[k] for k in ('station_id','status')} for s in report['stations']]}))

if __name__=='__main__': main()
