"""Explicit imports and bounded ASOS backfills; never activate stations or models.

CSV columns are an internal import contract, not a claim about provider exports.
Official metadata: https://www.data.go.kr/data/15114509/openapi.do
ASOS: https://www.data.go.kr/data/15059093/openapi.do
Season labels: https://data.kma.go.kr/climate/rainySeason/selectRainySeasonList.do
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from backend.external_observations import OfficialClient, SourceError, valid_rows

KWATER_URL = 'https://www.gims.go.kr/api/data/observationStationService/getGroundwaterMonitoringNetwork'


def stamp():
    return datetime.now(timezone.utc).isoformat()


def iso_day(value):
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError('invalid_date')
    return result


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result.astimezone(timezone.utc).isoformat()


def _envelope(raw, source, kind, collected_at):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', source):
        raise ValueError('invalid_provider')
    return dict(schema_version=1, kind=kind, source=source,
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                collected_at=timestamp(collected_at or stamp()),
                accepted=[], quarantined=[], blockers=[])


def import_csv(path, *, source, kind='observations', collected_at=None, today=None):
    """Import explicit canonical fields; missing values and conflicts stay quarantined.

    observations: source_station_id,date,value,unit,datum. Meter units only;
    datum is explicit ground_level_depth or elevation, never inferred or converted.
    rainy_seasons: year,region,start_date,end_date (region is an explicit label).
    CSV available_at, if present, is *not* trusted: first seen is import time.
    """
    raw = Path(path).read_bytes()
    result = _envelope(raw, source, kind, collected_at)
    if kind not in ('observations', 'rainy_seasons'):
        raise ValueError('unsupported_import_kind')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    required = (('source_station_id','date','value','unit','datum') if kind == 'observations'
                else ('year','region','start_date','end_date'))
    if not set(required) <= set(reader.fieldnames or []):
        raise ValueError('missing_csv_columns: ' + ','.join(required))
    today = today or datetime.now(ZoneInfo('Asia/Seoul')).date()
    groups = {}
    for line, row in enumerate(reader, 2):
        try:
            if any(not (row.get(k) or '').strip() for k in required):
                raise ValueError('missing_value')
            if kind == 'observations':
                day = iso_day(row['date'])
                if day >= today:
                    raise ValueError('future_or_unfinished_day')
                value = float(row['value'])
                if not math.isfinite(value):
                    raise ValueError('nonfinite_value')
                if row['unit'] != 'm' or row['datum'] not in ('ground_level_depth','elevation'):
                    raise ValueError('unit_or_datum_unverified')
                item = dict(provider=source, source_station_id=row['source_station_id'],
                            date=day.isoformat(), value=value, unit='m', datum=row['datum'],
                            metric='groundwater_level', quality='valid')
                key = (item['source_station_id'], item['date'])
            else:
                year = int(row['year']); a,b = iso_day(row['start_date']),iso_day(row['end_date'])
                if a > b or a.year != year or b.year != year or b >= today:
                    raise ValueError('invalid_season_range')
                item = dict(year=year, region=row['region'], start_date=a.isoformat(),
                            end_date=b.isoformat(), purpose='retrospective_evaluation_only')
                key = (year, item['region'])
            item.update(raw_sha256=result['raw_sha256'], collected_at=result['collected_at'],
                        available_at=result['collected_at'])
            groups.setdefault(key, []).append((line,item))
        except (ValueError, TypeError, OverflowError):
            result['quarantined'].append(dict(line=line, reason='invalid_or_unverified_row'))
    for group in groups.values():
        if len({json.dumps(item,sort_keys=True) for _,item in group}) > 1:
            result['quarantined'].extend(dict(line=n,reason='conflicting_observation') for n,_ in group)
        else:
            result['accepted'].append(group[0][1])
    result['accepted'].sort(key=lambda x: (str(x.get('source_station_id',x.get('region'))),str(x.get('date',x.get('year')))))
    return result


def collect_asos(start, end, station_id, *, output_dir, client=None, today=None):
    """31-day chunks, checked pagination, immutable raw pages; JSON output only.

    A failed run never returns accepted partial rows. Raw files remain for audit.
    No automatic station mapping, zero-fill, publication, or model activation.
    """
    a,b = iso_day(start),iso_day(end)
    today = today or datetime.now(ZoneInfo('Asia/Seoul')).date()
    if b<a or b>=today or (b-a).days>3660 or not station_id.isdigit():
        raise ValueError('invalid_backfill_range_or_station')
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=True)
    client=client or OfficialClient();collected_at=stamp();rows=[];pages=[]
    while a<=b:
        stop=min(a+timedelta(days=30),b);total=None;received=0
        for page in range(1,11):
            data,items,count=client.kma_page(a.isoformat(),stop.isoformat(),station_id,page)
            if count<0 or count>1000 or total is not None and count!=total:
                raise SourceError('kma: inconsistent pagination')
            total=count
            if not isinstance(items,list) or not items and received<count:
                raise SourceError('kma: incomplete pagination')
            raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
            key=os.getenv('KMA_ASOS_SERVICE_KEY','')
            if key:
                for secret in (key,unquote(key)):
                    raw=raw.replace(secret.encode(),b'[REDACTED]')
            digest=hashlib.sha256(raw).hexdigest();path=root/f'asos-{digest}.json'
            if not path.exists():path.write_bytes(raw)
            pages.append(dict(raw_sha256=digest,file=path.name,start_date=a.isoformat(),end_date=stop.isoformat(),page=page))
            received+=len(items);rows.extend(items)
            if received>=count:break
        if received!=total:
            raise SourceError('kma: incomplete pagination')
        a=stop+timedelta(days=1)
    good,bad=valid_rows(rows,'kma',start,end,station_id,today)
    result=dict(schema_version=1,kind='observations',source='kma_asos',collected_at=collected_at,
                accepted=[],quarantined=[{'reason':r['reason']} for r in bad],raw_pages=pages,blockers=[])
    for row in good:
        result['accepted'].append(dict(provider='kma_asos',source_station_id=station_id,date=row['date'],
            value=row['value'],metric='rainfall_mm',unit='mm',datum='precipitation',quality='valid',
            available_at=collected_at,collected_at=collected_at,
            raw_sha256=hashlib.sha256(json.dumps(pages,sort_keys=True).encode()).hexdigest()))
    return result


def collect_kwater(start, end, station_id, *, output_dir, client=None, today=None):
    """Collect raw JSON only. HTTP success is not validated observation success.

    Official endpoint and request fields are verified from GIMS opnDetail.do
    (multipart ser=APIR10) and https://www.gims.go.kr/js/opnApiService.js.
    Response envelope, units and datum remain unverified: never normalize or
    activate these payloads. No pagination is invented where none is documented.
    """
    key=os.getenv('GIMS_API_KEY','').strip()
    if not key:
        raise SourceError('kwater_auth_required')
    a,b=iso_day(start),iso_day(end)
    today=today or datetime.now(ZoneInfo('Asia/Seoul')).date()
    if b<a or b>=today or (b-a).days>3660 or not station_id.isdigit():
        raise ValueError('invalid_backfill_range_or_station')
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=True)
    client=client or OfficialClient();collected_at=stamp();pages=[]
    while a<=b:
        stop=min(a+timedelta(days=30),b)
        # OfficialClient limits retries, timeout and redirects; fixed messages only.
        try:
            data=client._json('kwater',KWATER_URL,dict(KEY=unquote(key),type='JSON',
                gennum=station_id,begindate=a.strftime('%Y%m%d'),enddate=stop.strftime('%Y%m%d')))
            raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        except Exception:
            raise SourceError('kwater_collection_failed') from None
        for secret in (key,unquote(key)):
            raw=raw.replace(secret.encode(),b'[REDACTED]')
        digest=hashlib.sha256(raw).hexdigest();path=root/f'kwater-{digest}.json'
        if not path.exists():path.write_bytes(raw)
        pages.append(dict(raw_sha256=digest,file=path.name,start_date=a.isoformat(),
                          end_date=stop.isoformat(),collected_at=collected_at))
        a=stop+timedelta(days=1)
    return dict(schema_version=1,kind='raw_observations',source='kwater',
        source_station_id=station_id,collected_at=collected_at,
        status='raw_collected_not_validated',accepted=[],quarantined=[],raw_pages=pages,
        blockers=['level_spec_and_response_unverified'],applied_to_forecasts=False)



def join_daily(levels, rainfall, *, station_id):
    """Join explicit selected sources; no implicit nearest-station approval.

    Caller must validate the station mapping. Conflicting dates and missing pairs
    are excluded; each row retains both source hashes and latest first-seen time.
    """
    grouped={}
    for metric,records in (('level',levels),('rain',rainfall)):
        for item in records:
            grouped.setdefault(item['date'],{'level':[],'rain':[]})[metric].append(item)
    accepted=[];quarantined=[]
    for day,pair in sorted(grouped.items()):
        if len(pair['level'])!=1 or len(pair['rain'])!=1:
            quarantined.append(dict(date=day,reason='missing_or_ambiguous_pair'));continue
        l,r=pair['level'][0],pair['rain'][0]
        if (l.get('metric')!='groundwater_level' or r.get('metric')!='rainfall_mm'
                or l.get('unit')!='m' or r.get('unit')!='mm'
                or l.get('quality')!='valid' or r.get('quality')!='valid'
                or l.get('datum') not in ('ground_level_depth','elevation')
                or not all(math.isfinite(x['value']) for x in (l,r)) or r['value']<0):
            quarantined.append(dict(date=day,reason='invalid_pair'));continue
        hashes=[l['raw_sha256'],r['raw_sha256']]
        digest=hashlib.sha256(json.dumps([station_id,day,l,r],sort_keys=True).encode()).hexdigest()
        accepted.append(dict(station_id=station_id,date=day,groundwater_level=l['value'],
            rainfall_mm=r['value'],level_unit='m',level_reference=l['datum'],
            available_at=max(timestamp(l['available_at']),timestamp(r['available_at'])),
            collected_at=max(timestamp(l['collected_at']),timestamp(r['collected_at'])),
            revision_id=digest,quality_status='valid',source_sha256=hashlib.sha256(''.join(hashes).encode()).hexdigest(),
            source_revisions=hashes))
    return dict(accepted=accepted,quarantined=quarantined)


def import_kma_rainy_csv(path, *, output_dir=None, collected_at=None, today=None):
    """Read the actual Korean CP949 KMA station-season export, evaluation only.

    Export preamble is preserved in raw bytes. Station labels are not geographic
    administrative regions and never automatically approve groundwater mapping.
    Missing precipitation summaries do not invalidate explicit season dates.
    """
    from collections import Counter
    raw=Path(path).read_bytes();digest=hashlib.sha256(raw).hexdigest()
    text=raw.decode('cp949');lines=text.splitlines()
    header='지점번호,지점명,시작일,종료일,장마일수,강수일수,합계강수량'
    indices=[i for i,line in enumerate(lines) if line.strip()==header]
    if len(indices)!=1:raise ValueError('kma_rainy_header_not_found')
    reader=csv.DictReader(lines[indices[0]:]);today=today or datetime.now(ZoneInfo('Asia/Seoul')).date()
    prior={}
    if output_dir is not None and (Path(output_dir)/'manifest.json').exists():
        prior=json.loads((Path(output_dir)/'manifest.json').read_text(encoding='utf-8'))
    stable_at=prior.get('collected_at') if prior.get('raw_sha256')==digest else None
    at=timestamp(collected_at or stable_at or stamp());accepted=[];quarantined=[];groups={};counts=Counter();raw_count=0
    source='https://data.kma.go.kr/climate/rainySeason/selectRainySeasonList.do'
    missing_rain=0
    for line,row in enumerate(reader,indices[0]+2):
        raw_count+=1
        try:
            sid=row['지점번호'].strip();name=row['지점명'].strip()
            a,b=iso_day(row['시작일'].strip()),iso_day(row['종료일'].strip())
            if not sid.isdigit() or not name or a.year!=b.year or b<a or b>=today:
                raise ValueError('invalid_station_or_season')
            duration=int(row['장마일수'])
            if duration!=(b-a).days+1:raise ValueError('duration_mismatch')
            counts[str(a.year)]+=1
            if not row['합계강수량'].strip():missing_rain+=1
            item=dict(year=a.year,region_code='kma_asos:'+sid,start_date=a.isoformat(),
                end_date=b.isoformat(),source_sha256=digest,evidence=[source,'official_station_csv_cp949'],
                usage='evaluation_only',source_station_id=sid,source_station_name=name,
                rainy_days=duration,available_at=at,collected_at=at,
                rainfall_days_raw=row['강수일수'],total_rainfall_raw=row['합계강수량'])
            groups.setdefault((a.year,sid),[]).append((line,item))
        except (ValueError,TypeError,KeyError,AttributeError):
            quarantined.append(dict(line=line,reason='invalid_station_season_or_duration'))
    for group in groups.values():
        if len({json.dumps(item,sort_keys=True) for _,item in group})>1:
            quarantined.extend(dict(line=n,reason='conflicting_station_year') for n,_ in group)
        else:accepted.append(group[0][1])
    accepted.sort(key=lambda r:(r['year'],int(r['source_station_id'])))
    station_ids=sorted({r['source_station_id'] for r in accepted},key=int)
    yearly={}
    for year in sorted({r['year'] for r in accepted}):
        actual={r['source_station_id'] for r in accepted if r['year']==year}
        yearly[str(year)]=dict(accepted=len(actual),missing_from_export_union=sorted(set(station_ids)-actual,key=int))
    result=dict(schema_version=1,kind='rainy_seasons',source='kma_station_rainy_csv',
        source_url=source,raw_sha256=digest,encoding='cp949',collected_at=at,
        accepted=accepted,quarantined=quarantined,raw_rows=raw_count,station_count=len(station_ids),
        yearly_coverage=yearly,missing_rainfall_summary_rows=missing_rain,
        coverage_note='Export completeness only; does not establish historical station operation or rainfall coverage.',
        blockers=['groundwater_to_weather_station_mapping_not_approved'])
    if output_dir is not None:
        root=Path(output_dir);root.mkdir(parents=True,exist_ok=True)
        raw_path=root/f'kma-rainy-{digest}.csv'
        if not raw_path.exists():raw_path.write_bytes(raw)
        canonical=root/'rainy-periods.csv'
        fields=['year','region','start_date','end_date','source_station_id','source_station_name','source_sha256']
        with canonical.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            for item in accepted:
                writer.writerow({k:(item['region_code'] if k=='region' else item[k]) for k in fields})
        manifest={k:v for k,v in result.items() if k!='accepted'}
        manifest.update(raw_file=raw_path.name,canonical_file=canonical.name,
            canonical_sha256=hashlib.sha256(canonical.read_bytes()).hexdigest(),accepted_rows=len(accepted))
        (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def parse_gims_station_layer(path, *, selection_path=None):
    """Normalize public map coordinates; retain unverified metadata state.

    Caller must fetch official Monitor/MapServer/0/query with outSR=4326.
    The source layer calls itself a standardization test layer, so coordinate
    presence does not approve source identity, levels or operational mapping.
    """
    raw=Path(path).read_bytes();data=json.loads(raw)
    if data.get('spatialReference',{}).get('wkid')!=4326 or data.get('exceededTransferLimit'):
        raise ValueError('coordinate_crs_or_completeness_unverified')
    options=json.loads(Path(selection_path).read_text()) if selection_path else {}
    digest=hashlib.sha256(raw).hexdigest();accepted=[];quarantined=[];seen=set()
    for feature in data.get('features',[]):
        try:
            a=feature['attributes'];g=feature['geometry'];sid=str(a['GENNUM'])
            lon,lat=float(g['x']),float(g['y'])
            if not sid.isdigit() or sid in seen or not 124<=lon<=132 or not 33<=lat<=39:
                raise ValueError('invalid_coordinate_or_identity')
            seen.add(sid)
            accepted.append(dict(station_id='kwater-'+sid,provider='kwater',source_station_id=sid,
                name=options.get(sid,a['OBSVRNAME']),region_code=a['SIDO_NM'],district_name=a['SIGUNGU_NM'],
                longitude=lon,latitude=lat,coordinate_crs='EPSG:4326',
                level_unit='unverified',level_reference='unverified',verified=False,
                evidence=['https://www.gims.go.kr/arcgis/rest/services/jihasu/Monitor/MapServer/0',
                    'public_official_map_query_outSR_4326'],source_sha256=digest,
                public_selection_match=sid in options,source_layer_quality='standardization_test_layer',
                blockers=['source_metadata_quality_review','level_datum_mapping_review']))
        except (KeyError,TypeError,ValueError,OverflowError):
            quarantined.append(dict(reason='invalid_station_feature'))
    return dict(accepted=accepted,quarantined=quarantined,source_sha256=digest,
        source_layer='https://www.gims.go.kr/arcgis/rest/services/jihasu/Monitor/MapServer/0',
        usage='map_inventory_unverified_not_model_activation')


AWS_MIN_URL='https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-aws2_min'
AWS_MIN_COLUMNS=('YYMMDDHHMI','STN','WD1','WS1','WDS','WSS','WD10','WS10','TA','RE','RN-15m','RN-60m','RN-12H','RN-DAY','HM','PA','PS','TD')


def parse_aws_snapshot(path, metadata_path, *, requested_at):
    """Separate KST minute snapshot. RN-DAY is unfinished daily accumulation.

    Exact source comments establish millimeters and <= -50 missing sentinels.
    Metadata joins require a single date-valid ID, never fuzzy name matches.
    """
    raw=Path(path).read_bytes();text=raw.decode('utf-8-sig');digest=hashlib.sha256(raw).hexdigest()
    moment=datetime.strptime(requested_at,'%Y%m%d%H%M').replace(tzinfo=ZoneInfo('Asia/Seoul'))
    if moment.strftime('%Y%m%d%H%M')!=requested_at:raise ValueError('invalid_aws_timestamp')
    if not text.strip().startswith('#START7777') or not text.strip().endswith('#7777END'):
        raise ValueError('incomplete_aws_snapshot')
    headers=[line.lstrip('#').split() for line in text.splitlines() if line.startswith('# YYMMDDHHMI')]
    if headers!=[list(AWS_MIN_COLUMNS)] or '-50 이하면' not in text:
        raise ValueError('unverified_aws_schema')
    metadata_raw=Path(metadata_path).read_bytes();metadata_hash=hashlib.sha256(metadata_raw).hexdigest()
    metadata=list(csv.DictReader(io.StringIO(metadata_raw.decode('cp949').lstrip())))
    date_value=moment.date().isoformat();observations=[];stations=[];quarantined=[];seen=set();unmatched=0
    for line_no,line in enumerate(text.splitlines(),1):
        if not line.strip() or line.startswith('#'):continue
        parts=line.split()
        try:
            if len(parts)!=len(AWS_MIN_COLUMNS) or parts[0]!=requested_at or not parts[1].isdigit():
                raise ValueError('invalid_row')
            sid=parts[1]
            if sid in seen:
                observations[:]=[r for r in observations if r['station_id']!='kma_aws:'+sid]
                stations[:]=[r for r in stations if r['station_id']!='kma_aws:'+sid]
                raise ValueError('duplicate_station')
            seen.add(sid);values={};quality={}
            for field in ('RN-15m','RN-60m','RN-12H','RN-DAY'):
                value=float(parts[AWS_MIN_COLUMNS.index(field)])
                if not math.isfinite(value):raise ValueError('nonfinite_rain')
                if value<=-50:values[field]=None;quality[field]='source_missing_or_error'
                elif value<0:values[field]=None;quality[field]='invalid_negative_rain'
                else:values[field]=value;quality[field]='valid'
            candidates=[m for m in metadata if m['지점']==sid and m['시작일']<=date_value and
                        (not m['종료일'] or m['종료일']>=date_value)]
            coordinate=None
            if len(candidates)==1:
                m=candidates[0]
                try:
                    lat,lon=float(m['위도']),float(m['경도'])
                    if not 33<=lat<=39 or not 124<=lon<=132:raise ValueError('outside_extent')
                    coordinate=dict(latitude=lat,longitude=lon,name=m['지점명'],
                        coordinate_valid_from=m['시작일'],coordinate_valid_to=m['종료일'] or None)
                except (ValueError,TypeError):pass
            if coordinate is None:unmatched+=1
            stations.append(dict(station_id='kma_aws:'+sid,source_station_id=sid,
                coordinate_status='matched_date_valid_id' if coordinate else 'metadata_missing_or_ambiguous',
                metadata_source_sha256=metadata_hash,**(coordinate or {})))
            observations.append(dict(station_id='kma_aws:'+sid,observed_at=moment.isoformat(),
                rainfall_mm=values,quality=quality,source_sha256=digest))
        except (ValueError,TypeError,IndexError):quarantined.append(dict(line=line_no,reason='invalid_aws_row'))
    if not observations:raise ValueError('no_aws_observations')
    return dict(schema_version=1,source='기상청 AWS 분자료',source_kind='observed',source_url=AWS_MIN_URL,
        observed_at=moment.isoformat(),unit='mm',raw_sha256=digest,metadata_sha256=metadata_hash,
        stations=stations,observations=observations,quarantined=quarantined,
        coordinates_matched=sum(r['coordinate_status']=='matched_date_valid_id' for r in stations),
        coordinates_unmatched=sum(r['coordinate_status']!='matched_date_valid_id' for r in stations),
        temporal_contract='minute_snapshot_accumulations_not_completed_daily_rainfall',
        available_fields=['RN-15m','RN-60m','RN-12H','RN-DAY'],
        note='Do not merge into ASOS DAY, infer missing as zero, or approve groundwater station mapping.')


def collect_aws_snapshot(requested_at, *, output_dir, session=None):
    """Fetch one official all-station minute snapshot, env key only, raw audit."""
    import requests
    key=os.getenv('KMA_APIHUB_KEY','').strip()
    if not key:raise SourceError('aws_auth_required')
    moment=datetime.strptime(requested_at,'%Y%m%d%H%M')
    if moment.strftime('%Y%m%d%H%M')!=requested_at:raise ValueError('invalid_aws_timestamp')
    try:
        response=(session or requests.Session()).get(AWS_MIN_URL,
            params=dict(tm2=requested_at,stn='0',help='1',authKey=key),timeout=(5,30),allow_redirects=False)
        if response.status_code!=200:raise SourceError('aws_http_failure')
        raw=response.content
        for secret in (key,unquote(key)):raw=raw.replace(secret.encode(),b'[REDACTED]')
        text=raw.decode('utf-8-sig')
        if not text.strip().startswith('#START7777') or not text.strip().endswith('#7777END'):
            raise SourceError('aws_incomplete_or_provider_error')
    except Exception:raise SourceError('aws_collection_failed') from None
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(raw).hexdigest();path=root/f'{digest}.txt'
    if not path.exists():path.write_bytes(raw)
    return dict(path=str(path),raw_sha256=digest,collected_at=stamp(),status='raw_collected')


AWS_DAY_URL='https://apihub.kma.go.kr/api/typ01/url/sfc_aws_day.php'


def parse_aws_daily(path, *, requested_date, collected_at=None, today=None):
    """Parse official rn_day seven-field CP949 export, distinct from minute data."""
    raw=Path(path).read_bytes();text=raw.decode('cp949');digest=hashlib.sha256(raw).hexdigest()
    day=datetime.strptime(requested_date,'%Y%m%d').date()
    if day.strftime('%Y%m%d')!=requested_date:raise ValueError('invalid_daily_date')
    today=today or datetime.now(ZoneInfo('Asia/Seoul')).date()
    if day>=today:raise ValueError('unfinished_daily_date')
    if not text.strip().startswith('#START7777') or not text.strip().endswith('#7777END'):
        raise ValueError('incomplete_aws_daily')
    headers=[line.lstrip('#').split() for line in text.splitlines() if line.startswith('# YYMMDD')]
    if headers!=[['YYMMDD','STN','LON','LAT','HT','VAL']]:raise ValueError('unverified_aws_daily_schema')
    at=timestamp(collected_at or stamp());groups={};quarantined=[]
    for number,line in enumerate(text.splitlines(),1):
        if not line.strip() or line.startswith('#'):continue
        try:
            fields=line.split(maxsplit=6)
            if len(fields)!=7 or fields[0]!=requested_date or not fields[1].isdigit():raise ValueError('invalid_row')
            sid=fields[1];lon,lat,height,value=map(float,fields[2:6])
            if not all(math.isfinite(x) for x in (lon,lat,height,value)) or not 124<=lon<=132 or not 33<=lat<=39 or value<0:
                raise ValueError('invalid_coordinate_or_rain')
            if not fields[6].strip():raise ValueError('missing_station_name')
            station=dict(station_id='kma_ground_aws_daily:'+sid,source_station_id=sid,name=fields[6],
                longitude=lon,latitude=lat,coordinate_source='same_official_daily_response',
                coordinate_valid_date=day.isoformat(),source_sha256=digest)
            observation=dict(station_id=station['station_id'],date=day.isoformat(),rainfall_mm=value,
                available_at=at,source_sha256=digest)
            groups.setdefault(sid,[]).append((station,observation))
        except (ValueError,TypeError):quarantined.append(dict(line=number,reason='invalid_daily_station_or_rain'))
    stations=[];observations=[]
    for sid,group in groups.items():
        if len(group)!=1:
            quarantined.append(dict(source_station_id=sid,reason='duplicate_station'));continue
        station,observation=group[0];stations.append(station);observations.append(observation)
    if not observations:raise ValueError('no_daily_rainfall')
    return dict(schema_version=1,source='기상청 지상·AWS 일강수',provider='kma_ground_aws_daily',
        source_url=AWS_DAY_URL,source_kind='observed',unit='mm',collected_at=at,
        unit_evidence=dict(api_element='obs=rn_day is daily precipitation in official API specification',
            api_specification_url='https://apihub.kma.go.kr/getAttachFile.do?fileName=지상및AWS일통계자료조회_API명세서.pdf',
            unit_reference_url='https://data.kma.go.kr/climate/extremum/selectExtremumList.do',
            unit_reference_label='일강수량(mm)',
            qualification='Combined interpretation of two official sources; API VAL table alone does not state mm.'),
        available_dates=[day.isoformat()],stations=sorted(stations,key=lambda x:int(x['source_station_id'])),
        observations=sorted(observations,key=lambda x:x['station_id']),quarantined=quarantined,
        collection_status='collected',raw_sha256=digest,
        temporal_contract='completed_calendar_day_KST_rn_day',
        quality_note='Separate station population from ASOS DAY; source zero preserved, negative/error values quarantined.')


def collect_aws_daily(requested_date, *, output_dir, session=None):
    import requests
    day=datetime.strptime(requested_date,'%Y%m%d').date()
    if day.strftime('%Y%m%d')!=requested_date or day>=datetime.now(ZoneInfo('Asia/Seoul')).date():
        raise ValueError('invalid_completed_daily_date')
    key=os.getenv('KMA_APIHUB_KEY','').strip()
    if not key:raise SourceError('aws_auth_required')
    try:
        response=(session or requests.Session()).get(AWS_DAY_URL,
            params=dict(tm2=requested_date,obs='rn_day',stn='0',disp='0',help='1',authKey=key),
            timeout=(5,30),allow_redirects=False)
        if response.status_code!=200:raise SourceError('aws_daily_http_failure')
        raw=response.content
        for secret in (key,unquote(key)):raw=raw.replace(secret.encode(),b'[REDACTED]')
        text=raw.decode('cp949')
        if not text.strip().startswith('#START7777') or not text.strip().endswith('#7777END'):
            raise SourceError('aws_daily_incomplete_or_provider_error')
    except Exception:raise SourceError('aws_daily_collection_failed') from None
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(raw).hexdigest();path=root/f'aws_daily-{digest}.txt'
    if not path.exists():path.write_bytes(raw)
    return dict(path=str(path),raw_sha256=digest,collected_at=stamp(),status='raw_collected')


WARNING_NOW_URL='https://apihub.kma.go.kr/api/typ01/url/wrn_now_data_new.php'


def parse_warning_snapshot(path, *, basis='f', requested_time=None, collected_at=None):
    """Fail closed: header-only HTTP success is not verified no-warning status.

    Official docs describe fields but do not establish empty-response semantics.
    Nonempty rows remain raw until a real positive response validates row layout
    (names have spaces; generic whitespace splitting is unsafe).
    """
    if basis not in ('f','e'):raise ValueError('invalid_warning_basis')
    if requested_time is not None:
        moment=datetime.strptime(requested_time,'%Y%m%d%H%M')
        if moment.strftime('%Y%m%d%H%M')!=requested_time:raise ValueError('invalid_warning_time')
    raw=Path(path).read_bytes();text=raw.decode('cp949');digest=hashlib.sha256(raw).hexdigest()
    lines=text.splitlines();headers=[line for line in lines if line.startswith('# REG_UP')]
    if '#START7777' not in text or len(headers)!=1 or not all(
        token in headers[0].split() for token in ('REG_UP','REG_ID','TM_FC','TM_EF','WRN','LVL','CMD','ED_TM')):
        raise ValueError('unverified_warning_response')
    rows=[line for line in lines if line.strip() and not line.startswith('#')]
    return dict(schema_version=1,source='기상청 특보현황',source_url=WARNING_NOW_URL,
        raw_sha256=digest,collected_at=timestamp(collected_at or stamp()),basis=basis,
        requested_time=requested_time,raw_row_count=len(rows),records=[],
        status='empty_response_unverified' if not rows else 'nonempty_response_schema_unverified',
        no_warnings_verified=False,complete_snapshot_verified=False,
        has_end_marker='#7777END' in text,
        blockers=['empty_response_semantics_unverified'] if not rows else ['positive_warning_row_layout_unverified'],
        note='Do not display an empty response as no active warnings or safe conditions.')


def collect_warning_snapshot(*, output_dir, basis='f', requested_time=None, session=None):
    import requests
    if basis not in ('f','e'):raise ValueError('invalid_warning_basis')
    if requested_time is not None:
        moment=datetime.strptime(requested_time,'%Y%m%d%H%M')
        if moment.strftime('%Y%m%d%H%M')!=requested_time:raise ValueError('invalid_warning_time')
    key=os.getenv('KMA_APIHUB_KEY','').strip()
    if not key:raise SourceError('warning_auth_required')
    try:
        response=(session or requests.Session()).get(WARNING_NOW_URL,
            params=dict(fe=basis,tm=requested_time or '',disp='0',help='1',authKey=key),
            timeout=(5,30),allow_redirects=False)
        if response.status_code!=200:raise SourceError('warning_http_failed')
        raw=response.content
        for secret in (key,unquote(key)):raw=raw.replace(secret.encode(),b'[REDACTED]')
        text=raw.decode('cp949')
        if '#START7777' not in text or '# REG_UP' not in text:raise SourceError('warning_provider_error')
    except Exception:raise SourceError('warning_collection_failed') from None
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(raw).hexdigest();path=root/f'warning-{digest}.txt'
    if not path.exists():path.write_bytes(raw)
    return dict(path=str(path),raw_sha256=digest,collected_at=stamp(),status='raw_collected_not_validated')


VILAGE_FORECAST_URL='https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst'


def _forecast_time(day,hour):
    result=datetime.strptime(day+hour,'%Y%m%d%H%M').replace(tzinfo=ZoneInfo('Asia/Seoul'))
    if result.strftime('%Y%m%d%H%M')!=day+hour:raise ValueError('invalid_forecast_time')
    return result


def _forecast_value(category,value):
    if category=='POP':
        number=float(value)
        if not math.isfinite(number) or not 0<=number<=100:raise ValueError('invalid_pop')
        return dict(kind='probability',value=number)
    if category=='PTY':
        if value not in ('0','1','2','3','4'):raise ValueError('invalid_pty')
        return dict(kind='precipitation_type_code',value=int(value))
    if value=='강수없음':return dict(kind='no_precipitation',lower_mm=0,upper_mm=0)
    if re.fullmatch(r'\d+(?:\.\d+)?',value):
        return dict(kind='numeric_or_qualitative_code_unverified',raw_code=value)
    match=re.fullmatch(r'(\d+(?:\.\d+)?)mm\s*(미만|이상)',value)
    if match:
        number=float(match[1]);return dict(kind='bounded_category',lower_mm=0 if match[2]=='미만' else number,
            upper_mm=number if match[2]=='미만' else None,upper_inclusive=False if match[2]=='미만' else None)
    match=re.fullmatch(r'(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)mm',value)
    if match and float(match[1])<=float(match[2]):
        return dict(kind='bounded_category',lower_mm=float(match[1]),upper_mm=float(match[2]),upper_inclusive=None)
    raise ValueError('unverified_pcp_category')


def parse_forecast_pages(paths, *, base_date, base_time, nx, ny, collected_at=None):
    """Validate complete source pages before exposing forecast-only rain items."""
    issued=_forecast_time(base_date,base_time);nx,ny=int(nx),int(ny)
    pages={};total=None;seen=set();items=[];raw_sources=[]
    for path in paths:
        raw=Path(path).read_bytes();response=json.loads(raw)['response']
        if str(response['header']['resultCode'])!='00':raise ValueError('forecast_provider_error')
        body=response['body'];page=int(body['pageNo']);size=int(body['numOfRows']);count=int(body['totalCount'])
        if page<1 or size<1 or count<1 or count>10000 or page in pages or total is not None and total!=count:
            raise ValueError('forecast_pagination_invalid')
        rows=body['items']['item']
        if not isinstance(rows,list) or len(rows)>size:raise ValueError('forecast_rows_invalid')
        pages[page]=(size,len(rows));total=count
        digest=hashlib.sha256(raw).hexdigest();raw_sources.append(dict(raw_sha256=digest,page=page))
        for row in rows:
            if (row['baseDate']!=base_date or row['baseTime']!=base_time or int(row['nx'])!=nx or int(row['ny'])!=ny):
                raise ValueError('forecast_request_mismatch')
            valid=_forecast_time(row['fcstDate'],row['fcstTime'])
            if valid<=issued:raise ValueError('forecast_before_issuance')
            key=(valid.isoformat(),row['category'])
            if key in seen:raise ValueError('duplicate_forecast')
            seen.add(key)
            category=row['category']
            if category not in ('POP','PCP','PTY'):continue
            value=str(row['fcstValue'])
            items.append(dict(valid_at=valid.isoformat(),category=category,value=value,
                unit=('source_category' if category=='PCP' and re.fullmatch(r'\d+(?:\.\d+)?',value) else {'POP':'%','PCP':'mm_per_hour_category','PTY':'code'}[category]),parsed=_forecast_value(category,value),
                raw_sha256=digest))
    if not pages or set(pages)!=set(range(1,max(pages)+1)) or sum(n for _,n in pages.values())!=total:
        raise ValueError('incomplete_forecast_pages')
    sizes={s for s,_ in pages.values()}
    if len(sizes)!=1 or any(n!=s for p,(s,n) in pages.items() if p!=max(pages)):
        raise ValueError('incomplete_forecast_pages')
    if not items:raise ValueError('no_rain_forecast')
    categories_by_time={}
    for item in items:categories_by_time.setdefault(item['valid_at'],set()).add(item['category'])
    if any(categories!={'POP','PCP','PTY'} for categories in categories_by_time.values()):
        raise ValueError('incomplete_rain_forecast_categories')
    return dict(schema_version=1,source='기상청 단기예보 격자 샘플',source_kind='forecast',
        source_url=VILAGE_FORECAST_URL,issued_at=issued.isoformat(),
        collected_at=timestamp(collected_at or stamp()),grid=dict(nx=nx,ny=ny,mapping_status='unverified',region_name=None),
        items=sorted(items,key=lambda r:(r['valid_at'],r['category'])),total_source_rows=total,
        page_count=len(pages),complete_pages=True,sample_only=True,raw_sources=raw_sources,
        observation_compatible=False,quality_note='Forecasts only; PCP numeric strings may be extended-range qualitative codes, never assumed exact mm. Extended forecasts may use 3-hour intervals.',
        category_source_url='https://data.kma.go.kr/community/nuriLovePopup.do',
        blockers=['grid_to_station_mapping_unverified','historical_as_issued_coverage_not_established'])


def collect_forecast_pages(base_date,base_time,nx,ny,*,output_dir,client=None):
    key=os.getenv('KMA_APIHUB_KEY','').strip()
    if not key:raise SourceError('forecast_auth_required')
    _forecast_time(base_date,base_time);nx,ny=int(nx),int(ny)
    if not 1<=nx<=200 or not 1<=ny<=300:raise ValueError('invalid_forecast_grid')
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=True);client=client or OfficialClient();paths=[];count=None
    for page in range(1,11):
        try:
            data=client._json('forecast',VILAGE_FORECAST_URL,dict(authKey=key,dataType='JSON',
                pageNo=page,numOfRows=1000,base_date=base_date,base_time=base_time,nx=nx,ny=ny))
            response=data['response']
            if str(response['header']['resultCode'])!='00':raise ValueError()
            body=response['body'];current=int(body['totalCount'])
            if current<1 or current>10000 or count is not None and count!=current:raise ValueError()
            count=current;raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
            for secret in (key,unquote(key)):raw=raw.replace(secret.encode(),b'[REDACTED]')
        except Exception:raise SourceError('forecast_collection_failed') from None
        digest=hashlib.sha256(raw).hexdigest();path=root/f'forecast-{digest}.json'
        if not path.exists():path.write_bytes(raw)
        paths.append(path)
        if page*1000>=count:break
    at=stamp();result=parse_forecast_pages(paths,base_date=base_date,base_time=base_time,nx=nx,ny=ny,collected_at=at)
    return result
