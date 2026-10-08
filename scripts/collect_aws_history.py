"""Acquire cached completed AWS days and assess unapproved rainfall candidates.

No station registry, mapping approval or model training is performed. Credentials
are read from the environment/local .env and never emitted into output files.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serving_app.national_sources import collect_aws_daily, parse_aws_daily

CANDIDATES = {'601739':'549','11775':'699','95537':'890'}


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False))
    temporary.replace(path)


def days(start,end):
    first,last = date.fromisoformat(start),date.fromisoformat(end)
    if last < first:
        raise ValueError('end precedes start')
    return [(first+timedelta(days=n)).isoformat() for n in range((last-first).days+1)]


def collect(day,cache):
    parsed_path = cache/'parsed'/(day+'.json')
    if parsed_path.exists():
        value = json.loads(parsed_path.read_text())
        if value.get('available_dates') == [day] and value.get('source_kind') == 'observed':
            return day,value,'cache'
    for attempt in range(3):
        try:
            fetched = collect_aws_daily(day.replace('-',''),output_dir=cache/'raw')
            value = parse_aws_daily(fetched['path'],requested_date=day.replace('-',''),collected_at=fetched['collected_at'])
            value['collection_attempts'] = attempt+1
            break
        except Exception:
            if attempt == 2:
                raise ValueError('collection_or_validation_failed') from None
            time.sleep(2*(attempt+1))
    value['raw_path'] = str(Path(fetched['path']).relative_to(ROOT)) if Path(fetched['path']).is_relative_to(ROOT) else str(fetched['path'])
    write(parsed_path,value)
    return day,value,'collected'


def longest(dates):
    run = best = 0
    previous = None
    for value in sorted(dates):
        current = date.fromisoformat(value)
        run = run+1 if previous and current-previous == timedelta(days=1) else 1
        best = max(best,run)
        previous = current
    return best


def latest_block(dates):
    ordered = sorted(dates)
    if not ordered:
        return []
    block = [ordered[-1]]
    for previous in reversed(ordered[:-1]):
        if date.fromisoformat(block[-1])-date.fromisoformat(previous) != timedelta(days=1):
            break
        block.append(previous)
    return list(reversed(block))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',required=True)
    parser.add_argument('--end',required=True)
    parser.add_argument('--workers',type=int,default=3,choices=(1,2,3))
    parser.add_argument('--cache-root',default='runtime/official/aws-history')
    parser.add_argument('--report',default='data/national_rainfall_training_readiness.json')
    parser.add_argument('--candidates',default='data/national_candidate_rainfall.json')
    args = parser.parse_args()
    # Loading does not print values or pass keys in process arguments.
    if not os.getenv('KMA_APIHUB_KEY'):
        from dotenv import load_dotenv
        load_dotenv(ROOT/'.env',override=False)
    if not os.getenv('KMA_APIHUB_KEY','').strip():
        print(json.dumps({'status':'blocked','reason':'credentials_required'}))
        return 2
    requested = days(args.start,args.end)
    cache = ROOT/args.cache_root
    fetched,errors,cached = {},[],0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(collect,day,cache):day for day in requested}
        for number,future in enumerate(as_completed(tasks),1):
            try:
                day,value,status = future.result()
                fetched[day] = value
                cached += status == 'cache'
            except Exception:
                errors.append({'date':tasks[future],'reason':'collection_or_validation_failed'})
            if number%10 == 0 or number == len(requested):
                print(json.dumps({'completed':number,'requested':len(requested),'valid_days':len(fetched),'failed_days':len(errors),'cached':cached}),flush=True)
    original = json.loads((ROOT/'data/national_training_readiness.json').read_text())
    source_stations = {s['source_station_id']:s for s in original['stations']}
    summaries,observations,source_refs = [],[],[]
    for day,payload in sorted(fetched.items()):
        source_refs.append({'date':day,'raw_sha256':payload['raw_sha256'],'raw_path':payload['raw_path'],
                            'collected_at':payload['collected_at'],'observations':len(payload['observations'])})
    for ground_id,weather_id in CANDIDATES.items():
        ground = source_stations[ground_id]
        valid,zero,coordinates = [],[],set()
        rainfall_rows = []
        for day,payload in sorted(fetched.items()):
            identifier = 'kma_ground_aws_daily:'+weather_id
            matches = [r for r in payload['observations'] if r['station_id'] == identifier]
            meta = next((r for r in payload['stations'] if r['station_id'] == identifier),None)
            if len(matches) != 1 or meta is None:
                continue
            row = matches[0]
            valid.append(day)
            if row['rainfall_mm'] == 0:
                zero.append(day)
            coordinates.add((meta['latitude'],meta['longitude'],meta['name']))
            rainfall_rows.append({**row,'source_station_id':weather_id,'groundwater_candidate_id':ground_id,
                'latitude':meta['latitude'],'longitude':meta['longitude'],'name':meta['name'],
                'collected_at':payload['collected_at'],'unit':'mm','source_kind':'observed','mapping_approved':False})
        observations.extend(rainfall_rows)
        absent = [d for d in requested if d not in valid]
        groundwater_days = set(days(original['period_start'],original['period_end']))
        groundwater_days -= set(ground.get('missing_days',[]))|set(ground.get('duplicate_days',[]))
        joint_days = [d for d in valid if d in groundwater_days]
        joint_longest = longest(joint_days)
        latest = latest_block(joint_days)
        latest_sufficient = len(latest)>=140 and latest[-1]==args.end
        summaries.append({'groundwater_source_station_id':ground_id,'groundwater_name':ground['name'],
            'weather_source_station_id':weather_id,'mapping_approved':False,'training_ready':False,
            'expected_days':len(requested),'valid_rainfall_days':len(valid),'missing_or_quarantined_dates':absent,
            'zero_rainfall_days':len(zero),'longest_consecutive_rainfall_days':longest(valid),
            'date_overlap_with_groundwater_days':len(joint_days),
            'longest_consecutive_overlap_days':joint_longest,
            'historical_m0_default_training_span_sufficient':joint_longest>=140,
            'latest_consecutive_overlap_days':len(latest),
            'latest_consecutive_overlap_start':latest[0] if latest else None,
            'latest_consecutive_overlap_end':latest[-1] if latest else None,
            'm0_default_training_span_sufficient':latest_sufficient,
            'one_step_20day_rainfall_samples_in_longest_block':max(0,longest(valid)-20),
            'same_id_coordinate_name_variants':[{'latitude':lat,'longitude':lon,'name':name} for lat,lon,name in sorted(coordinates)],
            'blockers':['station_specific_level_datum_contract_not_approved','historical_coordinate_changes_unverified',
                        'rainfall_mapping_not_approved']+(['matched_consecutive_rainfall_incomplete'] if absent else [])+
                       (['latest_training_span_below_current_national_140_day_minimum_or_stale'] if not latest_sufficient else [])})
    report = {'source':'KMA APIHub actual authenticated ground/AWS rn_day responses','source_kind':'observed',
        'period_start':args.start,'period_end':args.end,'expected_days':len(requested),'collected_days':len(fetched),
        'failed_days':errors,'cache_hits':cached,'max_parallel_requests':args.workers,'stations':summaries,
        'raw_sources':source_refs,'unit_evidence':next(iter(fetched.values()))['unit_evidence'] if fetched else {},
        'limitations':['Weather station proximity is an unapproved recommendation, not representative mapping.',
            'Groundwater overlap uses previously audited period coverage; no model-ready joined dataset is approved.',
            'Source zero preserved; missing/negative/quarantined source records are never replaced by zero.',
            'No station registration, mapping approval or model training performed.']}
    write(ROOT/args.report,report)
    write(ROOT/args.candidates,{'source_kind':'observed','unit':'mm','period_start':args.start,'period_end':args.end,
        'mapping_approved':False,'training_ready':False,'observations':observations})
    print(json.dumps({'status':'collected' if not errors else 'partial','days':len(fetched),
        'candidate_rows':len(observations),'candidates':[{'groundwater':s['groundwater_source_station_id'],
        'weather':s['weather_source_station_id'],'valid_days':s['valid_rainfall_days'],
        'longest':s['longest_consecutive_rainfall_days'],'latest':s['latest_consecutive_overlap_days']} for s in summaries]}),flush=True)
    return 0 if not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
