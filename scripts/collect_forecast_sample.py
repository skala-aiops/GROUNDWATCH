"""Collect or validate forecast-only grid sample, never observed rainfall."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.national_sources import collect_forecast_pages,parse_forecast_pages

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-date',required=True);p.add_argument('--base-time',required=True)
    p.add_argument('--nx',required=True,type=int);p.add_argument('--ny',required=True,type=int)
    p.add_argument('--raw',action='append',help='Complete saved JSON pages, repeat if needed')
    p.add_argument('--raw-dir',default='runtime/official/apihub');p.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        kw=dict(base_date=a.base_date,base_time=a.base_time,nx=a.nx,ny=a.ny)
        r=parse_forecast_pages(a.raw,**kw) if a.raw else collect_forecast_pages(output_dir=a.raw_dir,**kw)
        out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);temp=out.with_suffix('.tmp')
        temp.write_text(json.dumps(r,ensure_ascii=False,allow_nan=False));temp.replace(out)
        print(json.dumps(dict(status='parsed_forecast_only',items=len(r['items']),complete_pages=r['complete_pages'])));return 0
    except Exception:
        print(json.dumps(dict(status='failed',reason='forecast_collection_or_validation_failed')));return 2
if __name__=='__main__':raise SystemExit(main())
