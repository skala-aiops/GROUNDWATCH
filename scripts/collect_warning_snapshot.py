"""Collect raw warning status; never infer no warnings from an empty response."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serving_app.national_sources import collect_warning_snapshot,parse_warning_snapshot

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--basis',choices=['f','e'],default='f')
    p.add_argument('--time',help='KST YYYYMMDDHHMI; omit for supplier current time')
    p.add_argument('--raw',help='Parse saved CP949 response without network')
    p.add_argument('--raw-dir',default='runtime/official/apihub')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        f=None if a.raw else collect_warning_snapshot(output_dir=a.raw_dir,basis=a.basis,requested_time=a.time)
        r=parse_warning_snapshot(a.raw or f['path'],basis=a.basis,requested_time=a.time,collected_at=f['collected_at'] if f else None)
        out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,ensure_ascii=False))
        print(json.dumps(dict(status=r['status'],rows=r['raw_row_count'],no_warnings_verified=False)));return 0
    except Exception:
        print(json.dumps(dict(status='failed',reason='warning_collection_or_validation_failed')));return 2
if __name__=='__main__':raise SystemExit(main())
