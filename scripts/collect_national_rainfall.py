"""Collect explicit canonical ASOS station lists using env credentials only."""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.national_sources import collect_asos, iso_day


def collect(stations_path, periods, output_dir, workers=3):
    raw=Path(stations_path).read_bytes();metadata_hash=hashlib.sha256(raw).hexdigest()
    data=json.loads(raw);stations=data.get('stations',[]) if isinstance(data,dict) else data
    ids=[]
    for station in stations:
        sid=station['source_station_id']
        if not isinstance(sid,str) or not sid.isdigit() or sid in ids:
            raise ValueError('invalid_or_duplicate_station')
        ids.append(sid)
    if not ids or not 1<=workers<=3:raise ValueError('invalid_station_list_or_workers')
    for start,end in periods:
        if iso_day(start)>iso_day(end):raise ValueError('invalid_period')
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=True)
    def one(job):
        sid,start,end=job
        request=dict(station_id=sid,start_date=start,end_date=end,station_metadata_sha256=metadata_hash,
                     source='kma_asos',policy='strict_no_zero_fill_v1')
        identity=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        folder=root/sid/f'{start}_{end}';checkpoint=folder/'checkpoint.json';result_path=folder/'result.json'
        try:
            if checkpoint.exists() and result_path.exists():
                saved=json.loads(checkpoint.read_text())
                if saved.get('request_id')==identity and saved.get('result_sha256')==hashlib.sha256(result_path.read_bytes()).hexdigest():
                    return {**saved,'status':'cached'}
            folder.mkdir(parents=True,exist_ok=True)
            result=collect_asos(start,end,sid,output_dir=folder)
            payload=json.dumps(result,ensure_ascii=False,allow_nan=False).encode()
            temporary=folder/'result.json.tmp';temporary.write_bytes(payload);temporary.replace(result_path)
            report={**request,'request_id':identity,'status':'collected',
                    'accepted':len(result['accepted']),'quarantined':len(result['quarantined']),
                    'result_sha256':hashlib.sha256(payload).hexdigest()}
            temp=folder/'checkpoint.json.tmp';temp.write_text(json.dumps(report,ensure_ascii=False));temp.replace(checkpoint)
            return report
        except Exception:
            # Never echo provider responses, request URLs, paths or credentials.
            return {**request,'request_id':identity,'status':'failed','reason':'collection_failed'}
    jobs=[(sid,start,end) for sid in ids for start,end in periods]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:results=list(pool.map(one,jobs))
    report=dict(source='kma_asos',station_metadata_sha256=metadata_hash,station_count=len(ids),
                request_count=len(jobs),results=results,
                failed=sum(r['status']=='failed' for r in results))
    (root/'collection-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stations',required=True,help='Canonical JSON list or object with stations list')
    p.add_argument('--period',action='append',nargs=2,required=True,metavar=('START','END'))
    p.add_argument('--output-dir',required=True)
    p.add_argument('--workers',type=int,default=3,choices=[1,2,3])
    args=p.parse_args()
    try:r=collect(args.stations,args.period,args.output_dir,args.workers)
    except Exception:
        print(json.dumps({'status':'failed','reason':'invalid_inputs_or_storage'}));return 2
    print(json.dumps({k:v for k,v in r.items() if k!='results'}))
    return 2 if r['failed'] else 0

if __name__=='__main__':raise SystemExit(main())
