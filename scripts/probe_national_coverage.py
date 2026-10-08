"""Probe one explicit catalog candidate per region, retaining metadata and raw levels."""
import hashlib,json,os,sys,re
from pathlib import Path
from urllib.parse import unquote
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serving_app.external_observations import OfficialClient
from serving_app.national_sources import collect_kwater
from datetime import date,timedelta

def main():
    for line in (ROOT/'.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);os.environ.setdefault(key,value.strip().strip('\"\''))
    catalog=json.loads((ROOT/'data/national_stations_gims.json').read_text())['accepted']
    selected={}
    for s in catalog:selected.setdefault(s['region_code'],s)
    root=ROOT/'runtime/official/national-region-probe';root.mkdir(parents=True,exist_ok=True)
    endpoint=json.loads((ROOT/'data/national_source_probe.json').read_text())['station_metadata_endpoint']
    key=os.environ['GIMS_STATION_API_KEY'];client=OfficialClient();items=[]
    previous=json.loads((root/'report.json').read_text()) if (root/'report.json').exists() else {}
    cached={str(x['source_station_id']):x for x in previous.get('candidates',[])}
    end=(date.today()-timedelta(days=1));start=end-timedelta(days=30)
    for region,station in sorted(selected.items()):
        identifier=str(station['source_station_id']);item={'candidate_region':region,'source_station_id':identifier,
            'catalog_name':station['name'],'mapping_approved':False,'training_approved':False}
        try:
            data=client._json('gims_metadata',endpoint,dict(KEY=unquote(key),type='JSON',gennum=identifier,josacode='104'))
            raw=json.dumps(data,ensure_ascii=False).encode()
            for secret in (key,unquote(key)):raw=raw.replace(secret.encode(),b'[REDACTED]')
            digest=hashlib.sha256(raw).hexdigest();path=root/f'metadata-{digest}.json';path.write_bytes(raw)
            body=data.get('response',{});meta=body.get('resultData',[])
            provider_name=meta[0].get('jiguname') if isinstance(meta,list) and len(meta)==1 else None
            base_name=re.sub(r'\s*\((?:암반|충적)\)$','',station['name']).strip()
            item.update(metadata_sha256=digest,metadata_file=str(path.relative_to(ROOT)),
                metadata_name=provider_name,metadata_base_name_match=provider_name==base_name,
                metadata_result_code=body.get('resultCode'),metadata_rows=len(meta) if isinstance(meta,list) else None,
                metadata_name_match=bool(isinstance(meta,list) and len(meta)==1 and meta[0].get('jiguname')==station['name']))
            saved=cached.get(identifier,{})
            reusable=(previous.get('requested_start')==start.isoformat() and previous.get('requested_end')==end.isoformat() and saved.get('raw_pages'))
            result={'raw_pages':saved['raw_pages']} if reusable else collect_kwater(start.isoformat(),end.isoformat(),identifier,output_dir=root/identifier)
            pages=result['raw_pages'];rows=[]
            for page in pages:
                raw_page=(root/identifier/page['file']).read_bytes()
                if hashlib.sha256(raw_page).hexdigest()!=page['raw_sha256']:raise ValueError('raw_hash_mismatch')
                body=json.loads(raw_page).get('response',{})
                if body.get('resultCode')!='Success':raise ValueError('source_envelope_invalid')
                rows.extend(body.get('resultData',[]))
            item.update(observation_rows=len(rows),matching_station_rows=sum(str(r.get('gennum'))==identifier for r in rows),
                latest_raw_date=max((str(r.get('ymd')) for r in rows),default=None),
                raw_pages=pages,status='source_probe_complete' if body.get('resultCode')=='Success' and item.get('metadata_result_code')=='Success' else 'metadata_unverified')
        except Exception as exc:item.update(status='probe_failed',error_type=type(exc).__name__)
        items.append(item)
        (root/'report.json').write_text(json.dumps({'requested_start':start.isoformat(),'requested_end':end.isoformat(),
            'candidates':items,'applied_to_service':False},ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:v for k,v in item.items() if k not in ('raw_pages','metadata_file')},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
