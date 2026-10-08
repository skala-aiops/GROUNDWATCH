"""Frozen chronological seasonal experiment. Never emits prospective predictions."""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.national_models import NationalModelManager, _score
from backend.national_service import NationalService


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.replace(temporary, path)


def chronological_split(rows, start='2026-01-01', train_end='2026-05-31',
                        validation_end='2026-06-30', holdout_end='2026-10-07'):
    from datetime import date, timedelta
    boundaries=[date.fromisoformat(v) for v in (start,train_end,validation_end,holdout_end)]
    if not boundaries[0] < boundaries[1] < boundaries[2] < boundaries[3]:
        raise ValueError('strict chronological train/validation/holdout boundaries required')
    selected=[r for r in rows if start<=r['date']<=holdout_end]
    expected=(boundaries[-1]-boundaries[0]).days+1
    if len(selected)!=expected or selected[0]['date']!=start or selected[-1]['date']!=holdout_end:
        raise ValueError('complete consecutive experimental source required')
    if any(date.fromisoformat(b['date'])-date.fromisoformat(a['date'])!=timedelta(days=1) for a,b in zip(selected,selected[1:])):
        raise ValueError('consecutive observations required')
    train_count=sum(r['date']<=train_end for r in selected)-20
    validation_count=sum(train_end<r['date']<=validation_end for r in selected)
    holdout_count=sum(validation_end<r['date']<=holdout_end for r in selected)
    if train_count<60 or validation_count<21 or holdout_count<30:
        raise ValueError('training>=60 validation>=21 holdout>=30 targets required')
    return selected, {'train_start':selected[20]['date'],'train_end':train_end,'train_targets':train_count,
        'validation_start':(boundaries[1]+timedelta(days=1)).isoformat(),
        'validation_end':validation_end,'validation_targets':validation_count,
        'holdout_start':(boundaries[2]+timedelta(days=1)).isoformat(),
        'holdout_end':holdout_end,'holdout_targets':holdout_count,
        'context_days':20,'scaler_fit_end':train_end,'scaler_fit_scope':'train_only'}


def synthetic_seasonal_labels(rows):
    """Scenario calendar only, never official monsoon observations or features."""
    return {row['date']:['rainy' if '06-20'<=row['date'][5:]<='07-25' else 'non_rainy']
            for row in rows}


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


def _run(service, state_root, max_epochs=30, manager_factory=NationalModelManager,
         source_kind='observed', split_config=None, station_ids=None, max_variants=None):
    if source_kind not in ('observed','synthetic'):
        raise ValueError('explicit observed or synthetic evaluation required')
    split_config=dict(split_config or {})
    root=Path(state_root); report_path=root/('synthetic_seasonal_evaluation.json' if source_kind=='synthetic' else 'seasonal_evaluation.json')
    code_hash=_hash({name:hashlib.sha256((Path(__file__).resolve().parents[1]/name).read_bytes()).hexdigest()
        for name in ('backend/national_models.py','scripts/evaluate_national_seasons.py')})
    report=json.loads(report_path.read_text()) if report_path.exists() else {}
    if report.get('model_code_sha256') != code_hash or report.get('max_epochs') != max_epochs or report.get('source_kind','observed') != source_kind or report.get('split_config',{}) != split_config or report.get('station_ids') != station_ids:
        if report:
            archive=root/'seasonal-evaluation-reports'/report_path.stem/(_hash(report)+'.json')
            if not archive.exists():_atomic(archive,report)
        report={'schema_version':1,'evaluation_mode':'retrospective','operational_promotion_evidence':False,
            'status':'running','model_code_sha256':code_hash,'max_epochs':max_epochs,'stations':[],
            'source_kind':source_kind,'namespace':'national_synthetic_v1' if source_kind=='synthetic' else 'national_observed_v1',
            'simulation':source_kind=='synthetic','split_config':split_config,'station_ids':station_ids,
            'seasonal_label_scope':'synthetic_scenario' if source_kind=='synthetic' else 'official_station_period',
            'limitations':(['합성 시나리오 시간 분리 평가이며 실측 성능·미래 30일 운영 승격 증거가 아닙니다.',
                '합성 생성식에서의 상대 비교이며 현장 정확도의 증거가 아닙니다.'] if source_kind=='synthetic' else
                ['과거 관측의 시간 분리 평가이며 실제 발행 예측·미래 30일 승격 증거가 아닙니다.',
                 '해당 관측소·평가 구간의 결과이며 전국·모든 연도의 우수성을 주장하지 않습니다.'])}
    station_entries={s['station_id']:s for s in report['stations']}
    completed_this_process=0
    stations=[]; cursor=None
    while True:
        page=service.repo.list_stations(cursor=cursor,limit=200)
        stations.extend(s for s in page['items'] if s.get('source_contract_verified') and s.get('mapping_status')==('synthetic' if source_kind=='synthetic' else 'experimental') and s.get('source_kind','observed')==source_kind and (station_ids is None or s['station_id'] in station_ids))
        cursor=page.get('next_cursor')
        if not cursor: break
    for station in stations:
        station_id=station['station_id']
        try:
            rows,split=chronological_split(service.repo.observations(station_id),**split_config)
            labels=(synthetic_seasonal_labels(rows) if source_kind=='synthetic' else service.seasonal_labels(station_id,rows))
            source_hash=_hash({'station':station,'rows':rows,'evaluation_labels':labels})
            entry=station_entries.get(station_id)
            if not entry or entry.get('source_sha256')!=source_hash:
                entry={'station_id':station_id,'name':station['name'],'source_sha256':source_hash,
                    'split':split,'source_contract_verified':True,'operational_approved':False,
                    'seasonal_label_scope':'synthetic_scenario' if source_kind=='synthetic' else 'official_station_period',
                    'seasonal_label_calendar':{'start_mm_dd':'06-20','end_mm_dd':'07-25'} if source_kind=='synthetic' else None,
                    'weather_source_station_id':station.get('weather_source_station_id'),
                    'rainy_region':station.get('rainy_region'),'variants':{},'status':'running'}
                station_entries[station_id]=entry
            if entry.get('status') in ('failed','interrupted') and entry.get('source_sha256')==source_hash:
                continue
            experiment=_hash({'source':source_hash,'code':code_hash,'epochs':max_epochs})
            model_root=root/('synthetic-seasonal-evaluations' if source_kind=='synthetic' else 'seasonal-evaluations')/experiment
            manager=(NationalModelManager(model_root,namespace='national_synthetic_v1',source_kind='synthetic')
                     if source_kind=='synthetic' and manager_factory is NationalModelManager else manager_factory(model_root))
            guard=rows[split['train_targets']+split['validation_targets']:]
            for variant in ('M0','M1'):
                if entry['variants'].get(variant,{}).get('status')=='completed': continue
                entry['variants'][variant]={'status':'running','started_at':datetime.now(timezone.utc).isoformat()}
                entry['status']='running'
                report.update(stations=list(station_entries.values()),status='running')
                _atomic(report_path,report)
                trained=manager.train(station_id,rows,metadata=station,variant=variant,
                    validation_targets=split['validation_targets'],holdout_targets=split['holdout_targets'],max_epochs=max_epochs)
                version=trained['version']
                if trained['scaler']['fit_through']!=split['train_end'] or trained['holdout_start']!=split['holdout_start']:
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
                completed_this_process+=1
                if max_variants is not None and completed_this_process>=max_variants:
                    report['status']='running'
                    _atomic(report_path,report)
                    return report
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


def run(service,state_root,max_epochs=30,manager_factory=NationalModelManager,
        source_kind='observed',split_config=None,station_ids=None,max_variants=None):
    # One experiment writer across startup, manual container checks and restarts.
    import fcntl
    root=Path(state_root);root.mkdir(parents=True,exist_ok=True)
    from backend.worker_runtime import tensorflow_worker_lock
    with tensorflow_worker_lock(root), (root/('synthetic_seasonal_evaluation.lock' if source_kind=='synthetic' else 'seasonal_evaluation.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _run(service,state_root,max_epochs,manager_factory,source_kind,split_config,station_ids,max_variants)


def mark_interrupted(report_path):
    report=json.loads(report_path.read_text()) if report_path.exists() else {'stations':[]}
    report.update(status='interrupted',error='evaluation child interrupted; explicit retry required')
    for entry in report.get('stations',[]):
        if entry.get('status')=='running':
            entry['status']='interrupted'
            for variant in entry.get('variants',{}).values():
                if variant.get('status')=='running':variant['status']='interrupted'
    _atomic(report_path,report)


def run_variant_child(state_root,max_epochs,source_kind,split_config,station_ids,stop_requested=lambda:False):
    from backend.worker_runtime import run_isolated
    command=[sys.executable,str(Path(__file__).resolve()),'--once','--state-root',str(state_root),
             '--max-epochs',str(max_epochs),'--source-kind',source_kind]
    for key,value in (split_config or {}).items():command.extend(['--'+key.replace('_','-'),value])
    for station_id in station_ids or []:command.extend(['--station-id',station_id])
    return run_isolated(command,stop_requested=stop_requested)


def worker(state_root,max_epochs,source_kind='observed',split_config=None,station_ids=None):
    import signal
    import threading
    stopping=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopping.set())
    signal.signal(signal.SIGINT,lambda *_:stopping.set())
    enabled=os.getenv('GROUNDWATCH_SYNTHETIC_SEASONAL_EVALUATION_ENABLED' if source_kind=='synthetic' else 'GROUNDWATCH_SEASONAL_EVALUATION_ENABLED','false').lower() in ('1','true','yes')
    service=NationalService(state_root)
    while not stopping.is_set():
        if not enabled:
            stopping.wait(30)
            continue
        page=service.repo.list_stations(limit=200)
        stations=[s for s in page['items'] if s.get('source_contract_verified') and s.get('mapping_status')==('synthetic' if source_kind=='synthetic' else 'experimental') and s.get('source_kind','observed')==source_kind and (station_ids is None or s['station_id'] in station_ids)]
        # Bootstrap's ordinary model jobs take precedence over this isolated experiment.
        from backend.worker_runtime import has_pending_jobs
        busy=has_pending_jobs(service.store)
        complete=len(stations)>=(len(station_ids) if station_ids else 17 if source_kind=='synthetic' else 3)
        if complete:
            try:
                for station in stations: chronological_split(service.repo.observations(station['station_id']),**(split_config or {}))
            except ValueError: complete=False
        if busy or not complete:
            stopping.wait(5)
            continue
        report_path=Path(state_root)/('synthetic_seasonal_evaluation.json' if source_kind=='synthetic' else 'seasonal_evaluation.json')
        previous=json.loads(report_path.read_text()) if report_path.exists() else {}
        if previous.get('status')=='interrupted':
            stopping.wait(30)
            continue
        code=run_variant_child(state_root,max_epochs,source_kind,split_config,station_ids,stop_requested=stopping.is_set)
        if code:mark_interrupted(report_path)
        result=json.loads(report_path.read_text()) if report_path.exists() else {}
        stopping.wait(.5 if result.get('status')=='running' else 30)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',default=os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
    parser.add_argument('--max-epochs',type=int,default=int(os.getenv('GROUNDWATCH_SEASONAL_EVALUATION_EPOCHS','30')))
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--once',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--source-kind',choices=('observed','synthetic'),default='observed')
    parser.add_argument('--start')
    parser.add_argument('--train-end')
    parser.add_argument('--validation-end')
    parser.add_argument('--holdout-end')
    parser.add_argument('--station-id',action='append',dest='station_ids')
    args=parser.parse_args()
    split_config={key:getattr(args,key) for key in ('start','train_end','validation_end','holdout_end') if getattr(args,key)}
    if args.source_kind=='synthetic' and not split_config:
        split_config={'start':'2022-01-01','train_end':'2023-12-31','validation_end':'2024-03-31','holdout_end':'2025-12-31'}
    if args.worker:
        worker(args.state_root,args.max_epochs,args.source_kind,split_config,args.station_ids)
        return
    report_path=Path(args.state_root)/('synthetic_seasonal_evaluation.json' if args.source_kind=='synthetic' else 'seasonal_evaluation.json')
    if args.once:
        report=run(NationalService(args.state_root),args.state_root,args.max_epochs,source_kind=args.source_kind,split_config=split_config,station_ids=args.station_ids,max_variants=1)
    else:
        while True:
            code=run_variant_child(args.state_root,args.max_epochs,args.source_kind,split_config,args.station_ids)
            if code:
                mark_interrupted(report_path)
                raise SystemExit(code if code>0 else 128-code)
            report=json.loads(report_path.read_text())
            if report['status']!='running':break
    print(json.dumps({'status':report['status'],'stations':[{k:s[k] for k in ('station_id','status')} for s in report['stations']]}))

if __name__=='__main__': main()
