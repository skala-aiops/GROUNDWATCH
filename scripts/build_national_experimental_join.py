"""Build explicit retrospective experimental mappings; never grant operational approval."""
import argparse
import csv
from datetime import date, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.national_sources import join_daily
CANDIDATES={'601739':[('203','official_station_name'),('549','nearest_available_candidate')],
            '11775':[('165','official_station_name'),('699','nearest_available_candidate')],
            '95537':[('188','official_station_name'),('890','nearest_available_candidate')]}


def spans(days):
    blocks=[]
    for value in sorted(days):
        if not blocks or date.fromisoformat(value)-date.fromisoformat(blocks[-1][-1])!=timedelta(days=1):blocks.append([])
        blocks[-1].append(value)
    return {'longest':max(map(len,blocks),default=0),'latest':len(blocks[-1]) if blocks else 0,
            'latest_start':blocks[-1][0] if blocks else None,'latest_end':blocks[-1][-1] if blocks else None}


def build(root=ROOT):
    root=Path(root); history=json.load(gzip.open(root/'data/national_aws_history.json.gz','rt'))
    rainfall={}
    for row in history['observations']:
        key=(row['station_id'],row['date'])
        if key in rainfall:raise ValueError('duplicate_rainfall')
        rainfall[key]=row
    rain_provenance={r['date']:r for r in history['provenance']}
    readiness=json.loads((root/'data/national_training_readiness.json').read_text())
    ground={r['source_station_id']:r for r in readiness['stations']}
    rainy=list(csv.DictReader((root/'data/rainy_seasons_kma.csv').open()))
    mappings=[]
    for sid,candidates in CANDIDATES.items():
        folder=root/'runtime/official/national'/sid/'2026-01-01_2026-10-07'
        collection=json.loads((folder/'collection.json').read_text()); levels=[]; seen=set()
        for page in collection['raw_pages']:
            raw=(folder/page['file']).read_bytes();digest=hashlib.sha256(raw).hexdigest()
            if digest!=page['raw_sha256']:raise ValueError('groundwater_raw_hash_mismatch')
            payload=json.loads(raw)['response']
            if payload['resultCode']!='Success':raise ValueError('groundwater_response_failed')
            for r in payload['resultData']:
                day=date.fromisoformat(r['ymd'][:4]+'-'+r['ymd'][4:6]+'-'+r['ymd'][6:8]).isoformat()
                elev,depth=float(r['elev']),float(r['lev'])
                if r['gennum']!=sid or day in seen or not page['start_date']<=day<=page['end_date']:raise ValueError('invalid_groundwater_identity_or_date')
                if not math.isfinite(elev) or not math.isfinite(depth):raise ValueError('invalid_groundwater_number')
                if abs(elev+depth-ground[sid]['implied_ground_elevation_m'])>0.011:raise ValueError('elev_depth_spec_inconsistent')
                seen.add(day);levels.append(dict(date=day,value=elev,unit='m',datum='elevation',metric='groundwater_level',quality='valid',
                    available_at=page['collected_at'],collected_at=page['collected_at'],raw_sha256=digest,revision_id=digest))
        for weather_id,basis in candidates:
            rains=[];metas=[]
            for day in sorted(seen):
                record=rainfall.get(('kma_ground_aws_daily:'+weather_id,day))
                if record is None:continue
                rains.append(dict(date=day,value=record['rainfall_mm'],unit='mm',datum='precipitation',metric='rainfall_mm',quality='valid',
                    available_at=record['available_at'],collected_at=rain_provenance[day]['collected_at'],
                    raw_sha256=record['source_sha256'],revision_id=record['source_sha256']))
                metas.extend(s for s in history['station_metadata_by_date'][day] if s['source_station_id']==weather_id)
            mapping_id=f'gims-{sid}__kma-{weather_id}__experimental-v1'
            specpath=next((root/'runtime/official/national').glob('jewon-'+sid+'-*.json'))
            specraw=specpath.read_bytes();spec=json.loads(specraw)[0]
            if spec['GENNUM']!=sid:raise ValueError('wrong_station_specification')
            height_candidates=ground[sid]['nearest_weather_candidates']+ground[sid]['existing_asos_candidates']
            height=next((r['weather_elevation_m'] for r in height_candidates if r['source_station_id']==weather_id),None)
            mapping_evidence=dict(gims_source_url='https://www.gims.go.kr/obsvSelectJewon.do?gennum='+sid,
                gims_spec_sha256=hashlib.sha256(specraw).hexdigest(),gims_weather_name=spec['OBSNM'],
                gims_weather_code=spec['OBSV_CODE'],gims_weather_code_namespace_verified=False,
                selected_by_name_matches=any(m['name']==spec['OBSNM'] for m in metas),
                groundwater_ground_elevation_m=float(spec['ORIG_TMX']),weather_ground_elevation_m=height,
                weather_minus_groundwater_elevation_m=round(height-float(spec['ORIG_TMX']),3) if height is not None else None,
                elevation_qualification='Weather height is date-valid official KMA metadata candidate; groundwater height is independent GIMS specification.')
            joined=join_daily(levels,rains,station_id='kwater-'+sid)
            periods=[r for r in rainy if r['source_station_id']==weather_id]
            # Only the exact ASOS ID can supply its own rainy-season label.
            observations=[]
            for row in joined['accepted']:
                labels=[r for r in periods if r['start_date']<=row['date']<=r['end_date']]
                observations.append(dict(row,mapping_id=mapping_id,source_kind='observed',
                    rainy_season_evaluation_label=bool(labels) if periods else None))
            variants=sorted({(m['name'],m['latitude'],m['longitude']) for m in metas})
            lat1=math.radians(ground[sid]['latitude']);lon1=math.radians(ground[sid]['longitude'])
            distances=[]
            for _,lat,lon in variants:
                a=math.sin((math.radians(lat)-lat1)/2)**2+math.cos(lat1)*math.cos(math.radians(lat))*math.sin((math.radians(lon)-lon1)/2)**2
                distances.append(round(6371*2*math.asin(math.sqrt(a)),3))
            contract=dict(level_unit='m',level_reference='elevation',rainfall_unit='mm',
                evidence=['GIMS APIR10 elev=water level, lev=ground elevation minus level','Official graph water level el.m','Independent official yearbook sea-level elevation convention','280-day groundwater elev+lev consistency','Hash-verified completed KMA rn_day responses'])
            version=hashlib.sha256(json.dumps(dict(mapping=mapping_id,contract=contract,evidence=mapping_evidence),sort_keys=True).encode()).hexdigest()
            mappings.append(dict(mapping_id=mapping_id,mapping_evidence_version=version,
                groundwater_source_station_id=sid,weather_source_station_id=weather_id,
                mapping_status='experimental',selection_basis=basis,mapping_evidence=mapping_evidence,source_contract_verified=True,
                operational_approved=False,geographic_representativeness_verified=False,
                source_contract=contract,groundwater_name=ground[sid]['name'],
                weather_metadata_variants=[dict(name=n,latitude=lat,longitude=lon) for n,lat,lon in variants],
                distance_km_variants=distances,quality=dict(joined_days=len(observations),**spans(r['date'] for r in observations)),
                missing_pair_dates=[r['date'] for r in joined['quarantined']],
                rainy_region='kma_asos:'+weather_id if periods else None,
                rainy_periods=periods,observations=observations,
                limitations=['Retrospective evaluation only: actual first availability is 2026 collection time, not historical observation date.',
                    'Rainy labels are evaluation-only and must not be future-known model inputs.',
                    'Official GIMS weather codes are not assumed to be KMA station IDs.','No operational station approval, representative mapping approval or model training performed.']))
    return dict(schema_version=1,purpose='retrospective_experimental_training_candidates',operational_approved=False,
        rainfall_artifact_sha256=hashlib.sha256((root/'data/national_aws_history.json.gz').read_bytes()).hexdigest(),mappings=mappings)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',default='data/national_experimental_joined.json');args=parser.parse_args()
    result=build();path=ROOT/args.output;path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([dict(mapping=m['mapping_id'],quality=m['quality'],rainy_region=m['rainy_region']) for m in result['mappings']]))

if __name__=='__main__':main()
