"""Build observed rainfall snapshots from explicit collection request metadata."""
import argparse
from datetime import date,timedelta
import hashlib
import json
import math
from pathlib import Path


def build(root, output, stations_path=None):
    root=Path(root);output=Path(output)
    station_data=json.loads(Path(stations_path or root/'stations.json').read_text())
    stations=station_data.get('stations',[]) if isinstance(station_data,dict) else station_data
    selected={s['source_station_id']:s for s in stations}
    if len(selected)!=len(stations) or not selected:raise ValueError('duplicate or empty station metadata')
    report_path=next((p for p in (root/'collection-report.json',root/'report.json') if p.exists()),None)
    if report_path is None:raise ValueError('collection request metadata required')
    report=json.loads(report_path.read_text());requests=report['results'] if isinstance(report,dict) else report
    # Legacy reports omit end date. Obtain it from immutable saved raw-page metadata,
    # never from a hardcoded calendar. Failed legacy ranges without evidence block build.
    legacy_ends={}
    for path in root.glob('*/*/result.json'):
        result=json.loads(path.read_text())
        pages=result.get('raw_pages',[])
        if pages:
            start=min(p['start_date'] for p in pages);end=max(p['end_date'] for p in pages)
            if start in legacy_ends and legacy_ends[start]!=end:raise ValueError('ambiguous legacy period')
            legacy_ends[start]=end
    expected={};dates=set()
    for request in requests:
        sid=request.get('station_id',request.get('station'))
        start=request.get('start_date',request.get('start'))
        end=request.get('end_date') or legacy_ends.get(start)
        if sid not in selected or not end:raise ValueError('unselected station or missing period metadata')
        a,b=date.fromisoformat(start),date.fromisoformat(end)
        if b<a:raise ValueError('invalid requested period')
        key=(sid,start,end)
        if key in expected:raise ValueError('duplicate collection request')
        expected[key]=request
        while a<=b:dates.add(a.isoformat());a+=timedelta(days=1)
    if not expected:raise ValueError('empty collection requests')
    if isinstance(report,dict) and report.get('request_count')!=len(expected):
        raise ValueError('request count mismatch')
    observations=[];sources=[];collected=[];seen=set();finished=set()
    for path in sorted(root.glob('*/*/result.json')):
        sid=path.parent.parent.name
        matches=[key for key in expected if key[0]==sid and path.parent.name==f'{key[1]}_{key[2]}']
        if len(matches)!=1:raise ValueError('result outside selected request scope')
        request_key=matches[0];request=expected[request_key]
        if isinstance(request.get('status'),str) and request['status'] not in ('collected','cached'):
            # Stale success files cannot override a newly failed request.
            continue
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if request.get('result_sha256') and request['result_sha256']!=digest:raise ValueError('result hash mismatch')
        result=json.loads(raw)
        if result.get('source')!='kma_asos':raise ValueError('unexpected provider')
        for page in result.get('raw_pages',[]):
            if not request_key[1]<=page['start_date']<=page['end_date']<=request_key[2]:
                raise ValueError('raw page outside requested period')
        collected.append(result['collected_at']);finished.add(request_key)
        sources.append({'path':str(path.relative_to(root)),'sha256':digest,
            'accepted':len(result['accepted']),'quarantined':len(result['quarantined']),
            'raw_pages':result['raw_pages']})
        for row in result['accepted']:
            if row['source_station_id']!=sid or not request_key[1]<=row['date']<=request_key[2]:
                raise ValueError('observation station or date outside request')
            day=date.fromisoformat(row['date']).isoformat()
            if day!=row['date'] or not math.isfinite(row['value']) or row['value']<0:
                raise ValueError('invalid rainfall observation')
            key=('kma_asos:'+sid,day)
            if key in seen:raise ValueError('duplicate station/date')
            seen.add(key)
            observations.append({'station_id':key[0],'date':day,'rainfall_mm':row['value'],
                'available_at':row['available_at'],'source_sha256':row['raw_sha256']})
    if not observations:raise ValueError('no observed rainfall')
    obj={'schema_version':1,'source':'기상청 ASOS 일자료',
        'source_url':'https://www.data.go.kr/data/15059093/openapi.do',
        'metadata_source_url':'https://data.kma.go.kr/tmeta/stn/selectStnList.do',
        'source_kind':'observed','unit':'mm','collected_at':max(collected),
        'available_dates':sorted(dates),'stations':stations,
        'observations':sorted(observations,key=lambda r:(r['date'],r['station_id'])),
        'collection_status':'collected' if finished==set(expected) else 'partial_collection',
        'collection_results':len(sources),'expected_collection_results':len(expected),
        'quality_note':'Missing source cells remain absent/null. No interpolation or zero filling.',
        'sources':sources}
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(obj,ensure_ascii=False));temporary.replace(output)
    return {'stations':len(stations),'observations':len(observations),'results':len(sources),'status':obj['collection_status']}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='runtime/official/national-rainfall')
    parser.add_argument('--output',default='data/national_rainfall.json')
    parser.add_argument('--stations',help='Canonical JSON station list or snapshot; defaults to root/stations.json')
    args=parser.parse_args();print(json.dumps(build(args.root,args.output,args.stations)))
