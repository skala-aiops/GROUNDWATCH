"""Import cached public Seoul chart assignments without executing remote JavaScript."""
import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sys
from datetime import date,timedelta
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data.groundwater import REQUIRED_COLUMNS


def parse_chart(text):
    dates={int(i):value for i,value in re.findall(r'categories1\[(\d+)\]\s*=\s*"(\d{4}-\d{2}-\d{2})"\s*;',text)}
    fields={n:{int(i):value.strip() for i,value in re.findall(r'seriesData'+str(n)+r'\[(\d+)\]\s*=\s*([^;]*);',text)} for n in (1,4)}
    records=[]
    invalid=0
    for i,raw in dates.items():
        try:
            day=date.fromisoformat(raw)
            level=float(fields[1].get(i,''))
            rain=float(fields[4].get(i,''))
            if day>date.today() or not all(math.isfinite(v) for v in (level,rain)) or rain<0:
                raise ValueError('Invalid date/value')
            records.append((day,level,rain))
        except ValueError:
            invalid+=1
    return records,invalid


def import_cached(manifest_path,html_directory,output_directory,report_path):
    manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8-sig'))
    output=Path(output_directory)
    (output/'sources').mkdir(parents=True,exist_ok=True)
    rows=[]
    reports=[]
    common20=None
    common410=None
    for station in manifest['stations']:
        source=Path(html_directory)/f'groundwatch-official-observations-{station["district_code"]}.html'
        text=source.read_text(encoding='utf-8')
        if '수위 (gl.-m)' not in text or '강수량 (mm)' not in text:
            raise ValueError('Official table unit headers missing')
        parsed,invalid=parse_chart(text)
        groups={}
        for day,level,rain in parsed:
            groups.setdefault(day,set()).add((level,rain))
        valid={day:next(iter(values)) for day,values in groups.items() if len(values)==1}
        run=maxrun=0
        last=None
        ends20=set()
        ends410=set()
        for day in sorted(valid):
            run=run+1 if last and day-last==timedelta(days=1) else 1
            maxrun=max(maxrun,run)
            if run>=20:
                ends20.add(day)
            if run>=410:
                ends410.add(day)
            last=day
            level,rain=valid[day]
            rows.append(dict(station_id=station['station_id'],district_code=station['district_code'],date=day.isoformat(),groundwater_level=level,rainfall_mm=rain,level_unit='gl.-m'))
        common20=ends20 if common20 is None else common20&ends20
        common410=ends410 if common410 is None else common410&ends410
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.copyfile(source,output/'sources'/source.name)
        reports.append({'district_code':station['district_code'],'district_name':station['district_name'],
                        'station_id':station['station_id'],'station_name':station['station_name'],
                        'valid_rows':len(valid),'invalid_rows':invalid,'conflicting_days':sum(len(v)>1 for v in groups.values()),
                        'max_continuous_days':maxrun,'first_date':min(valid).isoformat() if valid else None,
                        'last_date':max(valid).isoformat() if valid else None,'source_sha256':digest,
                        'request_url':'https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrDta.do?'+urlencode(dict(schGuNm=station['district_name'],schObsvCode=station['station_id'],schFrDate=re.search(r'id="schFrDate"[^>]*value="([^"]+)"',text).group(1),schToDate=re.search(r'id="schToDate"[^>]*value="([^"]+)"',text).group(1)))})
        station['level_unit']='gl.-m'
        station['source_note']='Official Seoul observation HTML for explicit obsvCode; chart water/rain assignments parsed without executing JavaScript; table labels gl.-m/mm. No original-file sign conversion or imputation.'
    with (output/'canonical.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    manifest['approved']=False
    manifest['mapping_version']+='-official-source'
    manifest['source_type']='official_public_observation_chart'
    manifest['source_reference']='https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrDta.do'
    manifest['source_sha256']=hashlib.sha256((output/'canonical.csv').read_bytes()).hexdigest()
    manifest['limitations']=['Candidate representatives remain unapproved.','Source table water unit gl.-m; source-provided sign retained.','No missing-water/rain imputation.','Historical observations do not establish current real-time service.']
    (output/'representatives.candidates.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'source':'Official Seoul public observation HTML','unit':'gl.-m','rainfall_unit':'mm','raw_html_retained_outside_git':str(output/'sources'),
            'canonical_path':str(output/'canonical.csv'),'manifest_path':str(output/'representatives.candidates.json'),
            'representatives_approved':False,'districts':reports,'total_rows':len(rows),
            'common_20_day_end_count':len(common20 or set()),'latest_common_20_day_end':max(common20).isoformat() if common20 else None,
            'common_410_day_end_count':len(common410 or set()),'latest_common_410_day_end':max(common410).isoformat() if common410 else None,
            'canonical_sha256':manifest['source_sha256']}
    Path(report_path).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--html-directory',required=True)
    parser.add_argument('--output-directory',required=True)
    parser.add_argument('--report',required=True)
    args=parser.parse_args()
    result=import_cached(args.manifest,args.html_directory,args.output_directory,args.report)
    print(json.dumps({k:v for k,v in result.items() if k!='districts'},ensure_ascii=False))
