"""Collect explicit ASOS daily periods. Negative missing codes never become zero."""
import concurrent.futures
from datetime import date, timedelta, datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import requests
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
URL='https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd3.php'


def parse(raw,station,start,end):
    text=raw.decode('cp949')
    if '#START7777' not in text or '#7777END' not in text or '# 39. RN_DAY' not in text:
        raise ValueError('incomplete_or_error_response')
    rows=[];bad=[];seen=set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        fields=line.split()
        if len(fields)!=56:raise ValueError('unexpected_columns')
        day=date.fromisoformat(fields[0][:4]+'-'+fields[0][4:6]+'-'+fields[0][6:8]).isoformat()
        if fields[1]!=station or not start<=day<=end or day in seen:raise ValueError('identity_date_or_duplicate')
        seen.add(day);rain=float(fields[38])
        if not math.isfinite(rain) or rain<0:
            bad.append({'date':day,'raw_rainfall':fields[38],'reason':'source_missing_or_invalid'});continue
        rows.append({'date':day,'source_station_id':station,'rainfall_mm':rain,'raw_rainfall':fields[38],'unit':'mm'})
    return rows,bad


def main():
    load_dotenv(ROOT/'.env',override=False);key=os.environ['KMA_APIHUB_KEY']
    root=ROOT/'runtime/official/asos-hub-history-2020-2025';root.mkdir(parents=True,exist_ok=True)
    def one(station):
        rows=[];quarantined=[];sources=[];a=date(2020,1,1);last=date(2025,12,31)
        while a<=last:
            b=min(a+timedelta(days=30),last);p=root/f'{station}-{a}-{b}.txt'
            collected=datetime.now(timezone.utc).isoformat()
            meta=p.with_suffix('.metadata.json')
            if p.exists():
                raw=p.read_bytes()
                if meta.exists():
                    saved=json.loads(meta.read_text())
                    if saved['sha256']!=hashlib.sha256(raw).hexdigest():raise ValueError('cached_raw_hash_mismatch')
                    collected=saved['collected_at']
            else:
                response=requests.get(URL,params={'tm1':a.strftime('%Y%m%d'),'tm2':b.strftime('%Y%m%d'),'stn':station,'help':'1','authKey':key},timeout=45)
                if response.status_code!=200:raise ValueError(f'provider_http_status_{response.status_code}')
                raw=response.content.replace(key.encode(),b'[REDACTED]')
            accepted,bad=parse(raw,station,a.isoformat(),b.isoformat())
            if not p.exists():p.write_bytes(raw)
            if not meta.exists():meta.write_text(json.dumps({'collected_at':collected,'sha256':hashlib.sha256(raw).hexdigest()}))
            digest=hashlib.sha256(raw).hexdigest()
            for row in accepted:row.update(raw_sha256=digest,collected_at=collected,available_at=collected)
            rows.extend(accepted);quarantined.extend(bad);sources.append({'file':str(p.relative_to(ROOT)),'sha256':digest})
            a=b+timedelta(days=1)
        return {'source_station_id':station,'observations':rows,'quarantined':quarantined,'sources':sources}
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:stations=list(pool.map(one,['203','165','188']))
    result={'source':'kma_asos_apihub','source_url':URL,'period_start':'2020-01-01','period_end':'2025-12-31','stations':stations,'applied_to_service':False,'operational_promotion_evidence':False,'no_zero_fill':True}
    (ROOT/'data/national_asos_hub_history_2020_2025.json.gz').write_bytes(gzip.compress(json.dumps(result,ensure_ascii=False,allow_nan=False).encode(),mtime=0))
    print(json.dumps([{'station':s['source_station_id'],'accepted':len(s['observations']),'quarantined':len(s['quarantined'])} for s in stations]))
if __name__=='__main__':main()
