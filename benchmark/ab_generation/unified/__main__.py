import argparse
import json
from ..common import read
from .contract import entry_config
from .pipeline import build,fresh_life,produce

p=argparse.ArgumentParser(description='Opt-in unified generator. No simulation, UI, deployment, or main writes.')
s=p.add_subparsers(dest='command',required=True)
b=s.add_parser('build');b.add_argument('--inputs',required=True);b.add_argument('--out',required=True);b.add_argument('--config');b.add_argument('--workers',type=int,default=1)
a=s.add_parser('fresh-A');a.add_argument('--spec',required=True);a.add_argument('--world',required=True);a.add_argument('--portrait');a.add_argument('--config');a.add_argument('--out',required=True)
f=s.add_parser('fresh');f.add_argument('--life-batch',required=True);f.add_argument('--portraits',required=True);f.add_argument('--config');f.add_argument('--dates');f.add_argument('--out',required=True);f.add_argument('--workers',type=int,default=1)
args=p.parse_args();cfg=entry_config(args.config)
if args.command=='build':result=build(args.inputs,args.out,cfg,args.workers)
elif args.command=='fresh':result=produce(args.life_batch,args.portraits,args.out,cfg,args.workers,args.dates)
else:result=fresh_life(read(args.spec),read(args.world),read(args.portrait) if args.portrait else {},args.out,cfg)
print(json.dumps({k:v for k,v in result.items() if k not in ('A','service_ledger','ev_charging_steps')},ensure_ascii=False,indent=2))
