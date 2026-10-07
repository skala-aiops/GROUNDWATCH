"""Explicit source conversion; approved IDs/units are required inputs."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data.groundwater import convert_korean_source

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source',required=True)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--rainfall')
    parser.add_argument('--report',required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8-sig'))
    dataset = convert_korean_source(args.source,args.output,manifest,args.rainfall)
    Path(args.report).write_text(json.dumps(dataset.report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'accepted_rows':len(dataset.records),'report':args.report}))
