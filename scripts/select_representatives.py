"""Reproducible unapproved candidates from explicit source-name/official-code matches."""
import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data.groundwater import DISTRICTS, REQUIRED_COLUMNS


def select(source_path,mapping_path,official_directory,manifest_output,canonical_output):
    water, rain = defaultdict(set), defaultdict(set)
    with Path(source_path).open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            raw = row['관측일자']
            try:
                if len(raw)!=8 or not raw.isdigit():
                    continue
                day = date(int(raw[:4]),int(raw[4:6]),int(raw[6:8]))
                if day>date.today():
                    continue
            except ValueError:
                continue
            name, district = row['관측소 이름'].strip(),row['구'].strip()
            try:
                level=float(row['지하수위'])
                if name and district and math.isfinite(level):
                    water[(district,name,day)].add(level)
            except ValueError:
                pass
            try:
                value=float(row['일일강수량'])
                rain_name=row['강수량_측정소이름'].strip()
                if rain_name and math.isfinite(value) and value>=0:
                    rain[(rain_name,day)].add(value)
            except ValueError:
                pass
    mapping=defaultdict(set)
    with Path(mapping_path).open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            if row['관측소 이름'] and row['강수량_측정소이름']:
                mapping[(row['구'],row['관측소 이름'])].add(row['강수량_측정소이름'])
    official={}
    for i,district in enumerate(DISTRICTS):
        entries=json.loads((Path(official_directory)/f'groundwatch-official-stations-{i}.json').read_text())['result']
        names=defaultdict(set)
        for entry in entries:
            names[entry['obsvName']].add(entry['obsvCode'])
        official[district['district_name']]=names
    grouped=defaultdict(dict)
    conflicts=defaultdict(int)
    for (district,name,day),values in water.items():
        if len(values)==1:
            grouped[(district,name)][day]=next(iter(values))
        else:
            conflicts[(district,name)]+=1
    candidates,all_rows=[],[]
    available_by_district={}
    for district in DISTRICTS:
        options=[]
        for (gu,name),levels in grouped.items():
            if gu!=district['district_name'] or '관측종료' in name:
                continue
            ids=official[gu].get(name,set())
            rain_names=mapping.get((gu,name),set())
            if len(ids)!=1 or len(rain_names)!=1:
                continue
            rain_name=next(iter(rain_names))
            joined={day:(level,next(iter(rain[(rain_name,day)]))) for day,level in levels.items() if len(rain.get((rain_name,day),set()))==1}
            run=max_run=0
            last=None
            ends20=[]
            ends410=[]
            for day in sorted(joined):
                run=run+1 if last and day-last==timedelta(days=1) else 1
                max_run=max(max_run,run)
                if run>=20:
                    ends20.append(day)
                if run>=410:
                    ends410.append(day)
                last=day
            if not ends20:
                continue
            score=(bool(ends410), max(ends410) if ends410 else max(ends20),max_run,len(joined),-conflicts[(gu,name)],name)
            info={**district,'station_id':next(iter(ids)),'station_name':name,'source_station_name':name,
                  'rainfall_station_name':rain_name,'level_unit':'gl.-m',
                  'source_note':'Exact district/name match to Seoul public obsvCode lookup; official measurement table labels 수위 (gl.-m). Source CSV provenance and representative suitability still require team review.',
                  'source_reference':'https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrDta.do',
                  'id_reference':'https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrName.do',
                  'accepted_days':len(joined),'max_continuous_days':max_run,
                  'latest_20_day_as_of':max(ends20).isoformat(),
                  'latest_410_day_end':max(ends410).isoformat() if ends410 else None,
                  'water_conflicting_days':conflicts[(gu,name)]}
            options.append((score,info,joined,set(ends20),set(ends410)))
        if options:
            options.sort(key=lambda item:item[0],reverse=True)
            _,info,joined,ends20,ends410=options[0]
            candidates.append(info)
            available_by_district[district['district_code']]={'20':ends20,'410':ends410}
            for day,(level,rainfall) in sorted(joined.items()):
                all_rows.append(dict(station_id=info['station_id'],district_code=info['district_code'],date=day.isoformat(),groundwater_level=level,rainfall_mm=rainfall,level_unit='gl.-m'))
    common={}
    for length in ('20','410'):
        days=set.intersection(*(value[length] for value in available_by_district.values())) if len(available_by_district)==25 else set()
        common[length]={'common_end_dates':len(days),'latest_end':max(days).isoformat() if days else None}
    manifest={'approved':False,'mapping_version':'candidate-'+datetime.now().strftime('%Y%m%d'),
              'selection_policy':'Exact official district/name single-code match; unique provided rain mapping; quarantine water/rain conflicts; rank 410-day coverage then latest qualifying end then maximum run then accepted days then fewer conflicts; no model performance used.',
              'source_sha256':hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
              'stations':candidates,'coverage':common,
              'missing_districts':[d for d in DISTRICTS if d['district_code'] not in available_by_district],
              'rain_join':'Same explicitly mapped rain station/date pooled across all raw rows; no zero filling.',
              'limitations':['Unapproved candidates must not be used as production representatives.','gl.-m official table label verified; datum/sign interpretation not independently verified.','Shared station names require exact unique official code match.','Candidate CSV is historical source-derived data, not a claim of current or complete 25-district training readiness.']}
    Path(manifest_output).write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    Path(canonical_output).parent.mkdir(parents=True,exist_ok=True)
    with Path(canonical_output).open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    return {'candidate_districts':len(candidates),'canonical_rows':len(all_rows),'coverage':common,'manifest':str(manifest_output),'canonical':str(canonical_output)}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',required=True)
    parser.add_argument('--mapping',required=True)
    parser.add_argument('--official-directory',required=True)
    parser.add_argument('--manifest-output',required=True)
    parser.add_argument('--canonical-output',required=True)
    args=parser.parse_args()
    print(json.dumps(select(args.source,args.mapping,args.official_directory,args.manifest_output,args.canonical_output),ensure_ascii=False))
