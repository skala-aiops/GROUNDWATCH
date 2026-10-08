"""Collect or validate separate official ground/AWS completed daily rain."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.national_sources import collect_aws_daily,parse_aws_daily

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--date',required=True,help='Completed KST date YYYYMMDD')
    p.add_argument('--raw',help='Parse saved CP949 response without network')
    p.add_argument('--raw-dir',default='runtime/official/apihub')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        fetched=None if a.raw else collect_aws_daily(a.date,output_dir=a.raw_dir)
        r=parse_aws_daily(a.raw or fetched['path'],requested_date=a.date,
                          collected_at=fetched['collected_at'] if fetched else None)
        out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
        temp=out.with_suffix('.tmp');temp.write_text(json.dumps(r,ensure_ascii=False,allow_nan=False));temp.replace(out)
        print(json.dumps(dict(status='parsed',stations=len(r['stations']),observations=len(r['observations']),quarantined=len(r['quarantined']))));return 0
    except Exception:
        print(json.dumps(dict(status='failed',reason='aws_daily_collection_or_validation_failed')));return 2
if __name__=='__main__':raise SystemExit(main())
