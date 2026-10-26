#!/usr/bin/env python3
"""Apply an exact reviewed canonical catalog version and notify Skillwright automatically."""
import argparse
import json
from pathlib import Path
import sys

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--system',default=str(Path(__file__).resolve().parents[1]))
    sub=parser.add_subparsers(dest='action',required=True)
    apply=sub.add_parser('apply');apply.add_argument('--input',required=True)
    apply.add_argument('--expected-sha256',required=True);apply.add_argument('--by',required=True)
    retry=sub.add_parser('notify');retry.add_argument('--expected-sha256',required=True)
    args=parser.parse_args();system=Path(args.system).expanduser().resolve()
    sys.path.insert(0,str(system/'skillwright/tools'))
    from catalog_state import apply_catalog,notify
    try:
        if args.action=='apply':result=apply_catalog(system/'skillwright',Path(args.input).read_bytes(),args.expected_sha256,args.by)
        else:result=notify(system/'skillwright',args.expected_sha256)
    except Exception as error:print('catalog: '+str(error),file=sys.stderr);return 1
    print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
