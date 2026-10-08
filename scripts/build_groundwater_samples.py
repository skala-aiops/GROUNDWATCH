"""Build read-only GIMS source series; never approve station datum or training."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serving_app.national_sources import KWATER_URL

SOURCE_UNIT_EVIDENCE = [
    {'source_url':'https://www.gims.go.kr/opnDetail.do','request_form':{'ser':'APIR10'},
     'confirmed_labels':{'elev':'수위','lev':'심도, 원천 설명 lev(표고-수위)'},
     'scope':'API field names only; the output table alone does not specify units.'},
    {'source_url':'https://www.gims.go.kr/natnObsvStts.do',
     'confirmed_labels':{'elev':'수위(el.m)','lev':'심도(m)'},
     'scope':'Official graph labels; individual station vertical datum and source identity remain unapproved.'},
]


def longest(values):
    best = run = 0
    previous = None
    for value in sorted(values):
        current = date.fromisoformat(value)
        run = run+1 if previous is not None and current-previous==timedelta(days=1) else 1
        previous = current
        best = max(best,run)
    return best


def build(report,root):
    first,last = date.fromisoformat(report['period_start']),date.fromisoformat(report['period_end'])
    expected = [(first+timedelta(days=n)).isoformat() for n in range((last-first).days+1)]
    if not expected:
        raise ValueError('invalid period')
    stations,source_files = [],[]
    for station in report['stations']:
        identifier = station['source_station_id']
        grouped = defaultdict(list)
        invalid = []
        for source in station['raw_sources']:
            path = (root/source['file']).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError('raw path outside repository')
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != source['sha256']:
                raise ValueError('groundwater source hash mismatch')
            payload = json.loads(raw)
            response = payload.get('response',{})
            if response.get('resultCode') != 'Success' or not isinstance(response.get('resultData'),list):
                raise ValueError('unverified GIMS response envelope')
            source_files.append({'station_source_id':identifier,'file':source['file'],'sha256':digest,
                                 'raw_rows':len(response['resultData'])})
            for row in response['resultData']:
                try:
                    if str(row['gennum']) != identifier:
                        raise ValueError('source station mismatch')
                    moment = datetime.strptime(str(row['ymd']),'%Y%m%d').date()
                    if moment.strftime('%Y%m%d') != str(row['ymd']) or not first<=moment<=last:
                        raise ValueError('source date outside requested range')
                    elev,lev = float(row['elev']),float(row['lev'])
                    if not math.isfinite(elev) or not math.isfinite(lev):
                        raise ValueError('nonfinite source values')
                    grouped[moment.isoformat()].append({'date':moment.isoformat(),
                        'elev':elev,'lev':lev,'groundwater_level':elev,
                        'raw_elev':str(row['elev']),'raw_lev':str(row['lev']),
                        'source_sha256':digest,'quality_status':'valid'})
                except (KeyError,TypeError,ValueError):
                    invalid.append({'source_sha256':digest,'raw_ymd':str(row.get('ymd','')),
                                    'reason':'invalid_identity_date_or_value'})
        observations,valid,missing,duplicates = [],[],[],[]
        for day in expected:
            matches = grouped[day]
            if len(matches) == 1:
                observations.append(matches[0]);valid.append(day)
            else:
                if matches:
                    duplicates.append(day)
                else:
                    missing.append(day)
                observations.append({'date':day,'elev':None,'lev':None,'groundwater_level':None,
                    'raw_elev':None,'raw_lev':None,'source_sha256':None,
                    'quality_status':'duplicate' if matches else 'missing'})
        stations.append({'station_id':'gims-sample-'+identifier,'source_station_id':identifier,
            'name':station['name'],'latitude':station.get('latitude'),'longitude':station.get('longitude'),
            'coordinate_status':'candidate_catalog_location_historical_changes_unverified',
            'historical_coordinates_verified':False,'verified':False,'model_ready':False,
            'training_approved':False,'mapping_approved':False,'unit':'el.m',
            'source_unit_label':'원천 수위(el.m)','depth_unit':'m','depth_source_unit_label':'원천 심도(m)',
            'level_reference_status':'station_datum_unapproved','source_url':KWATER_URL,
            'source_information_url':'https://www.gims.go.kr/natnObsvStts.do',
            'observations':observations,
            'quality':{'expected_days':len(expected),'valid_days':len(valid),'missing_dates':missing,
                'duplicate_dates':duplicates,'invalid_rows':invalid,'longest_consecutive_days':longest(valid),
                'negative_raw_depth_days':sum(r['lev'] is not None and r['lev']<0 for r in observations)}})
    return {'schema_version':1,'source_kind':'observed','source':'GIMS 국가지하수 실측 원천 샘플',
        'source_url':KWATER_URL,'period_start':first.isoformat(),'period_end':last.isoformat(),
        'available_dates':expected,'generated_at':datetime.now(timezone.utc).isoformat(),
        'station_count':len(stations),'observation_count':sum(s['quality']['valid_days'] for s in stations),
        'source_fields':{'elev':{'label':'원천 수위','source_unit_label':'el.m'},
                         'lev':{'label':'원천 심도','source_unit_label':'m'}},
        'source_unit_evidence':SOURCE_UNIT_EVIDENCE,'stations':stations,'raw_sources':source_files,
        'display_contract':'groundwater_level is a display-only alias of unchanged source elev, not a training-ready canonical value.',
        'limitations':['Station-specific vertical datum/source contract and historical coordinates remain unapproved.',
            'No sign inversion, GL conversion, depth/elevation substitution, interpolation or missing-zero fill performed.',
            'These are three obtained sample stations, not all nationwide stations or nationwide prediction coverage.',
            'No registry, representative manifest, mapping approval or model training changed.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--readiness',default='data/national_training_readiness.json')
    parser.add_argument('--output',default='data/national_groundwater_samples.json')
    args = parser.parse_args()
    result = build(json.loads((ROOT/args.readiness).read_text()),ROOT)
    output = ROOT/args.output
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary = output.with_name(output.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
    temporary.replace(output)
    print(json.dumps({'stations':result['station_count'],'valid_observations':result['observation_count'],
        'raw_files_verified':len(result['raw_sources']),'model_ready':False,'output':str(output.relative_to(ROOT))}))


if __name__ == '__main__':
    main()
