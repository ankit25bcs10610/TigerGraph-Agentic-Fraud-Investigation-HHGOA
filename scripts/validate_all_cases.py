#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
parser=argparse.ArgumentParser(); parser.add_argument("--cases-dir",type=Path,required=True); parser.add_argument("--reference-catalog",type=Path,required=True)
if __name__=="__main__":
 args=parser.parse_args(); files=sorted(args.cases_dir.glob("*.json"));
 if not files: raise SystemExit("no case JSON files found")
 for path in files: subprocess.run([sys.executable,"scripts/validate_case_output.py",str(path),"--reference-catalog",str(args.reference_catalog)],check=True)
