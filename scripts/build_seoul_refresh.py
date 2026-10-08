"""Validate authenticated-by-identity public Seoul HTML into a separate observed delta.

Never replaces the frozen base CSV, representative approval, or model artifacts.
"""
import argparse,csv,hashlib,json,re,sys
from collections import defaultdict
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.import_official_groundwater import parse_chart
from data.groundwater import REQUIRED_COLUMNS


def validated_rows(text,station,start,end):
    codes=re.findall(r'var\s+obsvCode\s*=\s*[\"\']([^\"\']+)[\"\']\s*;',text)
    if codes!=[station['station_id']]:raise ValueError('station_identity_mismatch')
    if '수위 (gl.-m)' not in text or '강수량 (mm)' not in text:raise ValueError('source_unit_missing')
    records,invalid=parse_chart(text)
    grouped=defaultdict(list)
    for day,level,rain in records:
        if start<=day.isoformat()<=end:grouped[day.isoformat()].append((level,rain))
    rows=[];duplicates=[]
    for day,values in sorted(grouped.items()):
        if len(values)!=1:duplicates.append(day);continue
        level,rain=values[0]
        rows.append(dict(station_id=station['station_id'],district_code=station['district_code'],
            date=day,groundwater_level=level,rainfall_mm=rain,level_unit='gl.-m'))
    dates={r['date'] for r in rows};run=0;maxrun=0;previous=None
    for day in sorted(dates):
        current=date.fromisoformat(day)
        run=run+1 if previous and current-previous==timedelta(days=1) else 1
        maxrun=max(maxrun,run);previous=current
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    expected={(a+timedelta(days=i)).isoformat() for i in range((b-a).days+1)}
    return rows,dict(valid_rows=len(rows),invalid_rows=invalid,duplicate_dates=duplicates,
        missing_dates=sorted(expected-dates),longest_consecutive_days=maxrun,
        latest_date=max(dates,default=None))


def build(report_path,output):
    original=ROOT/'data/groundwater_observations.csv';original_hash=hashlib.sha256(original.read_bytes()).hexdigest()
    manifest=json.loads((ROOT/'data/representatives.json').read_text())
    by_id={s['station_id']:s for s in manifest['stations']}
    report=json.loads(Path(report_path).read_text());rows=[];audit=[];seen=set()
    for item in report['seoul']:
        if item['station_id'] in seen:raise ValueError('duplicate_station_report')
        seen.add(item['station_id']);station=by_id[item['station_id']]
        path=(ROOT/item['raw_file']).resolve()
        if not path.is_relative_to(ROOT/'runtime'):raise ValueError('raw_path_outside_runtime')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['raw_sha256']:raise ValueError('source_hash_mismatch')
        valid,quality=validated_rows(raw.decode('utf-8'),station,report['requested_start'],report['requested_end'])
        rows.extend(valid);audit.append({'station_id':station['station_id'],'district_code':station['district_code'],
            'district_name':station['district_name'],'raw_sha256':item['raw_sha256'],**quality})
    if seen!=set(by_id):raise ValueError('requires_all_fixed_representatives')
    if any(r['date']<='2024-03-18' for r in rows):raise ValueError('delta_overlaps_frozen_base')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=REQUIRED_COLUMNS,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    result={'source':'서울특별시 물순환정보 공개시스템','source_url':'https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrDta.do',
        'collected_at':report['collected_at'],'source_kind':'observed','unit':'gl.-m','rainfall_unit':'mm',
        'requested_start':report['requested_start'],'requested_end':report['requested_end'],
        'stations':audit,'station_count':len(audit),'rows':len(rows),
        'canonical_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'frozen_base_sha256':original_hash,
        'applied_to_service':False,'model_training_performed':False,
        'limitations':['Missing days remain missing; no rainfall imputation.',
            'A valid public HTML response does not establish same-day data availability.',
            'Frozen base CSV, representative approval and model evaluation partitions are unchanged.']}
    assert hashlib.sha256(original.read_bytes()).hexdigest()==original_hash
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',required=True)
    p.add_argument('--output',default='data/seoul_observation_extension.csv');a=p.parse_args()
    result=build(a.report,a.output)
    Path('data/seoul_observation_extension_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'stations':result['station_count'],'rows':result['rows'],'applied_to_service':False}))
