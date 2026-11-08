"""Explicit household-only CLI; never invokes models, EnergyPlus, or collectors."""
import argparse
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description='Reusable survey-supported household scenario generator')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare-sources',help='Decode explicitly supplied supported raw files into a normalized source pool')
    p.add_argument('--data-config',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    p=sub.add_parser('make-example-pool',help='Create entirely invented public test records')
    p.add_argument('--out',required=True,type=Path);p.add_argument('--records-per-country',type=int,default=40)
    p=sub.add_parser('generate',help='Generate a new cohort without overwriting existing outputs')
    p.add_argument('--pool',required=True,type=Path);p.add_argument('--config',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--data-config',type=Path)
    p=sub.add_parser('verify',help='Recheck a frozen run and byte-replay its final projection')
    p.add_argument('run',type=Path);p.add_argument('--data-config',type=Path)
    p=sub.add_parser('render-cards',help='Write complete household cards from an existing cohort')
    p.add_argument('run',type=Path)
    args=parser.parse_args()
    if args.command=='prepare-sources':
        from .sources import prepare
        prepare(args.data_config,args.out)
    elif args.command=='make-example-pool':
        from .fixtures import make_pool
        make_pool(args.out,args.records_per_country)
    elif args.command=='generate':
        from .pipeline import generate
        generate(args.pool,args.config,args.out,args.data_config)
    elif args.command=='verify':
        from .pipeline import verify
        verify(args.run,args.data_config)
    elif args.command=='render-cards':
        from .cards import render
        render(args.run)
if __name__=='__main__':main()
