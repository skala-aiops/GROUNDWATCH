from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serving_app.groundwater.training import train_all
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepared',default='serving_app/models/groundwater/prepared');parser.add_argument('--output',default='serving_app/models/groundwater/trained');parser.add_argument('--epochs',type=int,default=35);parser.add_argument('--only')
    args=parser.parse_args();train_all(args.prepared,args.output,args.epochs,args.only)
