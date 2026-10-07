"""지하수 CSV 전처리. 원본 단위 gl.-m는 서울시 원본 시스템에서 확인했습니다."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serving_app.groundwater.prepare import prepare
if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();report=prepare(args.source,args.output)
    print(report['counts'])
    for station in report['selected']:
        print(station['district'],station['station'],station['window_count'],station['latest_usable_date'],station['operational_days'],flush=True)
