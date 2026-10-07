"""Audit supplied joined Korean CSV without inventing missing rain or source units."""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


def audit(path):
    path = Path(path)
    stations, districts, missing, groups = set(), set(), Counter(), {}
    rows = invalid_dates = future_dates = nonpositive = 0
    with path.open(encoding='utf-8-sig',newline='') as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            rows += 1
            name = row.get('관측소 이름','').strip()
            district = row.get('구','').strip()
            if name:
                stations.add(name)
            if district:
                districts.add(district)
            for key,value in row.items():
                if not value or not value.strip():
                    missing[key] += 1
            try:
                raw_date = row['관측일자']
                if len(raw_date) != 8 or not raw_date.isdigit():
                    raise ValueError('Expected YYYYMMDD')
                day = date(int(raw_date[:4]),int(raw_date[4:6]),int(raw_date[6:8]))
            except (KeyError,ValueError):
                invalid_dates += 1
                continue
            if day > date.today():
                future_dates += 1
                continue
            try:
                level = float(row['지하수위'])
                rain = float(row['일일강수량'])
                if level <= 0:
                    nonpositive += 1
            except (KeyError,ValueError):
                continue
            if not name or not district:
                continue
            key = (name,day)
            groups.setdefault(key,[]).append((level,rain,district))
    conflicts = {key for key,values in groups.items() if len(set(values)) > 1}
    continuous = defaultdict(set)
    by_station = defaultdict(list)
    for (name,day),values in groups.items():
        if (name,day) not in conflicts and '관측종료' not in name:
            by_station[(name,values[0][2])].append(day)
    for (name,district),days in by_station.items():
        days.sort()
        run = 0
        previous = None
        for day in days:
            run = run+1 if previous and day-previous == timedelta(days=1) else 1
            if run >= 20:
                continuous[district].add(day.isoformat())
            previous = day
    common = set.intersection(*(continuous.get(d,set()) for d in districts)) if districts else set()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return {'source_file':path.name,'sha256':digest.hexdigest(),'rows':rows,
            'station_names':len(stations),'districts':len(districts),'missing_by_column':dict(missing),
            'invalid_date_rows':invalid_dates,'future_date_rows':future_dates,
            'nonpositive_level_rows_with_numeric_rain':nonpositive,
            'conflicting_station_date_groups':len(conflicts),
            'duplicate_extra_rows_with_numeric_values':sum(len(v)-1 for v in groups.values()),
            'common_20_day_as_of_count':len(common),'latest_common_20_day_as_of':max(common) if common else None,
            'district_latest_continuous_20_day_as_of':{d:max(continuous[d]) if continuous[d] else None for d in sorted(districts)},
            'limitations':['Station names are not verified physical well identifiers.','Source groundwater unit and measurement reference remain unverified.','Conflicting groups are quarantined; no arbitrary averaging or rainfall imputation.','Twenty-day input coverage does not imply sufficient training coverage.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('paths',nargs='+')
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    output = {'generated_at':datetime.now().astimezone().isoformat(),'audit_type':'provided_joined_csv_read_only','sources':[audit(p) for p in args.paths]}
    Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':args.output,'sources':len(output['sources'])}))
