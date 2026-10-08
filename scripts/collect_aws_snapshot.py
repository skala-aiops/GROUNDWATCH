"""Collect/parse separate official minute AWS rainfall snapshots; no service activation."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.national_sources import collect_aws_snapshot,parse_aws_snapshot

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--time',required=True,help='KST YYYYMMDDHHMI')
    p.add_argument('--metadata',required=True,help='Official KMA CP949 station metadata CSV')
    p.add_argument('--raw',help='Parse saved source instead of contacting supplier')
    p.add_argument('--raw-dir',default='runtime/official/apihub')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        fetched=None if a.raw else collect_aws_snapshot(a.time,output_dir=a.raw_dir)
        r=parse_aws_snapshot(a.raw or fetched['path'],a.metadata,requested_at=a.time)
        if fetched:r['collected_at']=fetched['collected_at']
        output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(r,ensure_ascii=False,allow_nan=False))
        print(json.dumps(dict(status='parsed',rows=len(r['observations']),coordinates_matched=r['coordinates_matched'],coordinates_unmatched=r['coordinates_unmatched'])))
        return 0
    except Exception:
        print(json.dumps(dict(status='failed',reason='aws_collection_or_validation_failed')));return 2
if __name__=='__main__':raise SystemExit(main())
