#!/usr/bin/env python3
"""Resolve a tool-guide path; never create directories or write files."""
import argparse
import os
from pathlib import Path
import re
import sys

KINDS=('cli','mcp','plugin','service','schedule','external-app')

def resolve(kind,tool,workspace=None):
    if kind not in KINDS: raise ValueError('tool kind is unresolved')
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]*',tool) or tool in ('.','..'):
        raise ValueError('tool must be one lowercase guide name')
    root=Path(os.environ.get('FOXRUN_HOME',str(Path.home()/'.foxrun'))).expanduser().resolve()
    if workspace is not None:
        sys.path.insert(0,str(root))
        from base import paths
        root=paths.workspace(workspace)
    directory=root/'tools'/kind
    if not directory.is_dir(): raise ValueError('drawn owner directory is missing: '+str(directory))
    return directory/(tool+'.md')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',required=True)
    parser.add_argument('--tool',required=True)
    parser.add_argument('--workspace')
    args=parser.parse_args()
    try: print(resolve(args.kind,args.tool,args.workspace))
    except (ValueError,ImportError) as e: parser.exit(2,'Hold: cannot place tool guide: '+str(e)+'\n')

if __name__=='__main__':main()
