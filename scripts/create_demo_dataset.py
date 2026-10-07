"""실제 관측 자료와 분리된 재현용 합성 CSV를 명시적으로 생성합니다."""
import argparse
import csv
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.groundwater import DISTRICTS

def create(output, days=510):
    if days < 410:
        raise ValueError('최소 410일이 필요합니다.')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    stations = [{**d, 'station_id': f'SYNTHETIC-{d["district_code"]}',
                 'station_name': f'{d["district_name"]} 합성 검증 관측소',
                 'level_unit': 'synthetic-m', 'source_note': '수학 함수 생성, 실제 관측값 아님'} for d in DISTRICTS]
    manifest = {'mapping_version': 'synthetic-v1', 'approved': True, 'source_kind': 'synthetic',
                'description': '파이프라인 검증 전용. 실제 서울시 관측 자료·성능으로 보고하지 않습니다.',
                'stations': stations}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    with (output / 'observations.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['station_id','district_code','date','groundwater_level','rainfall_mm','level_unit'])
        writer.writeheader()
        for index, station in enumerate(stations):
            for day in range(days):
                phase = 2 * math.pi * day / 12
                writer.writerow({'station_id': station['station_id'], 'district_code': station['district_code'],
                    'date': (date(2024,1,1)+timedelta(days=day)).isoformat(),
                    'groundwater_level': round(10 + index/10 + 3*math.sin(phase), 8),
                    'rainfall_mm': round(8+6*math.cos(phase), 8), 'level_unit': 'synthetic-m'})
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='runtime/demo')
    parser.add_argument('--days', type=int, default=510)
    args = parser.parse_args()
    print(create(args.output, args.days))
