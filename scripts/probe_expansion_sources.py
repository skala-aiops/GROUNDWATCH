"""Read-only expansion audit: immutable raw sources, no registry/model mutation."""
from __future__ import annotations
import argparse
from datetime import date,datetime,timezone,timedelta
import hashlib,json,os,re,sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.import_official_groundwater import parse_chart
from backend.national_sources import collect_kwater
SEOUL_URL='https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrDta.do'


def seoul_probe(station,start,end,root,session=None):
    response=(session or requests.Session()).get(SEOUL_URL,params={
        'schGuNm':station['district_name'],'schObsvCode':station['station_id'],
        'schFrDate':start,'schToDate':end},timeout=(5,25),allow_redirects=False)
    if response.status_code!=200:return {'status':'http_error','http_status':response.status_code}
    raw=response.content;digest=hashlib.sha256(raw).hexdigest()
    path=root/f'seoul-{digest}.html'
    if not path.exists():path.write_bytes(raw)
    text=response.text
    unit_verified='수위 (gl.-m)' in text and '강수량 (mm)' in text
    records,invalid=parse_chart(text)
    selected=re.findall(r'<option[^>]*value=[\"\']([^\"\']+)[\"\'][^>]*selected',text,re.I)
    returned_codes=re.findall(r'var\s+obsvCode\s*=\s*[\"\']([^\"\']+)[\"\']\s*;',text)
    identity_verified=(len(returned_codes)==1 and returned_codes[0]==station['station_id'])
    if not returned_codes:identity_verified=station['station_id'] in selected
    bounded=[r for r in records if start<=r[0].isoformat()<=end]
    valid=bounded if unit_verified and identity_verified else []
    return {'status':'observations_found' if valid else 'no_valid_observations',
        'identity_verified':identity_verified,'unit_verified':unit_verified,
        'parsed_rows':len(records),'requested_range_rows':len(valid),'invalid_rows':invalid,
        'latest_source_date':max((r[0].isoformat() for r in records),default=None),
        'latest_valid_date':max((r[0].isoformat() for r in valid),default=None),
        'outside_requested_range_rows':len(records)-len(bounded),
        'raw_file':str(path.relative_to(ROOT)),'raw_sha256':digest}


def gims_probe(station,year,root):
    result=collect_kwater(f'{year}-01-01',f'{year}-01-31',station,output_dir=root)
    rows=[];envelopes=[]
    for page in result['raw_pages']:
        response=json.loads((root/page['file']).read_text()).get('response',{})
        envelopes.append(response.get('resultCode'))
        items=response.get('resultData',[])
        if isinstance(items,list):rows.extend(items)
    matched=[r for r in rows if str(r.get('gennum'))==station and re.fullmatch(f'{year}01[0-9]{{2}}',str(r.get('ymd','')))]
    return {'status':'raw_rows_found' if matched and all(c=='Success' for c in envelopes) else 'no_verified_rows',
        'response_codes':envelopes,'raw_row_count':len(rows),'matching_row_count':len(matched),
        'raw_pages':result['raw_pages'],'training_approved':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seoul-limit',type=int,default=25)
    p.add_argument('--start',default='2024-03-19')
    p.add_argument('--history-years',type=int,nargs='*',default=[2020,2024])
    p.add_argument('--output',default='runtime/official/expansion-probe')
    args=p.parse_args()
    for line in (ROOT/'.env').read_text().splitlines() if (ROOT/'.env').exists() else []:
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);os.environ.setdefault(key,value.strip().strip('\"\''))
    root=(ROOT/args.output).resolve()
    if not root.is_relative_to(ROOT/'runtime'):raise ValueError('raw_output_must_be_in_runtime')
    root.mkdir(parents=True,exist_ok=True)
    end=(date.today()-timedelta(days=1)).isoformat()
    report={'collected_at':datetime.now(timezone.utc).isoformat(),'requested_start':date.fromisoformat(args.start).isoformat(),
        'requested_end':end,'seoul':[],'gims_history':[],'applied_to_service':False}
    stations=json.loads((ROOT/'data/representatives.json').read_text())['stations']
    for station in stations[:max(0,args.seoul_limit)]:
        item={'station_id':station['station_id'],'district_name':station['district_name']}
        try:item.update(seoul_probe(station,report['requested_start'],end,root))
        except requests.RequestException:item.update(status='network_error')
        report['seoul'].append(item)
        print(json.dumps(item,ensure_ascii=False),flush=True)
    for station in ['601739','11775','95537']:
        for year in args.history_years:
            item={'source_station_id':station,'year':year}
            try:item.update(gims_probe(station,year,root))
            except Exception as exc:item.update(status='collection_failed',error_type=type(exc).__name__)
            report['gims_history'].append(item)
            print(json.dumps({k:v for k,v in item.items() if k!='raw_pages'},ensure_ascii=False),flush=True)
    name=root/'report.json';name.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('report:',str(name.relative_to(ROOT)))

if __name__=='__main__':main()
