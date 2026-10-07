"""사용자 제공 서울 CSV를 보간 없이 일별 연속 학습 구간으로 정제합니다."""
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
import csv
import hashlib
import json
import math

SEQUENCE_LENGTH = 20
UNIT_SOURCE = 'https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrDta.do'


def contiguous_segments(rows):
    segments = []
    for row in sorted(rows, key=lambda r: r['observed_date']):
        if not segments or date.fromisoformat(row['observed_date']) - date.fromisoformat(segments[-1][-1]['observed_date']) != timedelta(days=1):
            segments.append([])
        segments[-1].append(row)
    return segments


def window_indices(rows):
    """Target index requires exactly 20 preceding consecutive calendar days."""
    result, streak = [], 0
    for index, row in enumerate(rows):
        consecutive = index and date.fromisoformat(row['observed_date']) - date.fromisoformat(rows[index-1]['observed_date']) == timedelta(days=1)
        streak = streak + 1 if consecutive else 1
        if streak >= SEQUENCE_LENGTH + 1:
            result.append(index)
    return result


def prepare(source, destination):
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    grouped, locations = defaultdict(lambda: defaultdict(set)), {}
    counts = Counter()
    with source.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        needed = {'구','관측소 이름','관측일자','지하수위','일일강수량'}
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError('서울 통합 CSV의 필수 열이 없습니다.')
        for row in reader:
            counts['source_rows'] += 1
            key = (row['구'].strip(), row['관측소 이름'].strip())
            try:
                day = datetime.strptime(row['관측일자'], '%Y%m%d').date()
                level, rain = Decimal(row['지하수위']), Decimal(row['일일강수량'])
                if not key[0] or not key[1] or not level.is_finite() or not rain.is_finite() or day > date.today():
                    raise ValueError()
                if rain < 0 or rain*10 != (rain*10).to_integral_value():
                    raise ValueError()
                values = (float(level), float(rain))
                if not all(math.isfinite(v) for v in values):
                    raise ValueError()
            except (ValueError, InvalidOperation):
                counts['invalid_rows'] += 1
                continue
            grouped[key][day.isoformat()].add(values)
            locations[key] = row.get('위치', '')
    candidates, retained = [], {}
    for (district, station), days in grouped.items():
        rows, conflicts, nonpositive = [], 0, 0
        for day, values in sorted(days.items()):
            if len(values) != 1:
                conflicts += 1
                continue
            depth_m, rainfall = next(iter(values))
            if depth_m <= 0:
                nonpositive += 1
                continue
            rows.append({'observed_date': day, 'groundwater_depth_cm': round(depth_m * 100, 6), 'rainfall_mm': rainfall})
        segments = contiguous_segments(rows)
        operational = [s for s in segments if len(s) >= 41]
        sample_count = len(window_indices(rows))
        eligible = bool(operational and sample_count >= 120 and '관측종료' not in station)
        entry = dict(district=district, station=station, valid_rows=len(rows), window_count=sample_count,
                     conflict_dates=conflicts, nonpositive_dates=nonpositive, latest_source_date=max(days),
                     longest_segment=max(map(len, segments), default=0), eligible=eligible,
                     latest_usable_date=operational[-1][-1]['observed_date'] if operational else '',
                     operational_days=len(operational[-1]) if operational else 0)
        candidates.append(entry)
        retained[(district, station)] = (rows, operational[-1] if operational else [])
    selected = []
    districts = sorted({k[0] for k in grouped})
    for district in districts:
        pool = [c for c in candidates if c['district'] == district and c['eligible']]
        if not pool:
            raise ValueError(f'{district}: 최소 120개 학습 창과 41일 연속 구간을 갖는 관측소가 없습니다.')
        # Availability selection only. Forecast errors/test scores never select stations.
        pool.sort(key=lambda c: (-date.fromisoformat(c['latest_usable_date']).toordinal(), -c['window_count'], c['station']))
        best = pool[0].copy()
        rows, operational = retained[(district, best['station'])]
        rows = [r for r in rows if r['observed_date'] <= operational[-1]['observed_date']]
        identity = str(uuid5(NAMESPACE_URL, 'groundwatch:seoul:'+district+':'+best['station']))
        code = 'SEOUL-' + identity[:8].upper()
        best.update(well_id=identity, code=code, name=district+' · '+best['station'], location=locations[(district,best['station'])],
                    first_date=rows[0]['observed_date'], last_date=rows[-1]['observed_date'], selected_rows=len(rows),
                    rows_file=code+'.json', operational_file=code+'.csv')
        (destination/best['rows_file']).write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        with (destination/best['operational_file']).open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['observed_date','groundwater_depth_cm','rainfall_mm']);writer.writeheader();writer.writerows(operational)
        selected.append(best)
    counts['unique_station_dates'] = sum(len(days) for days in grouped.values())
    counts['duplicate_rows'] = counts['source_rows'] - counts['invalid_rows'] - counts['unique_station_dates']
    counts['conflicting_station_dates'] = sum(c['conflict_dates'] for c in candidates)
    counts['nonpositive_station_dates'] = sum(c['nonpositive_dates'] for c in candidates)
    report = dict(source_name=source.name,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),counts=dict(counts),
                  unit={'source_depth':'gl.-m','output_depth':'cm','factor':100,'rainfall':'mm','evidence_url':UNIT_SOURCE},
                  selection='관측종료 제외; 최소 120개 연속 21일 창; 최근 41일 이상 연속 구간 종료일, 창 수, 관측소 이름 순',
                  selected=selected,candidates=candidates)
    (destination/'preparation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
