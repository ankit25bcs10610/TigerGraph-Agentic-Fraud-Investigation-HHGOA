#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from backend.app.output.models import CaseOutput
from backend.app.output.validator import CatalogResolver, StopContext, validate_output
parser=argparse.ArgumentParser(); parser.add_argument("case_file",type=Path); parser.add_argument("--reference-catalog",type=Path,required=True); parser.add_argument("--independent-evidence-count",type=int,default=0); parser.add_argument("--verification-settled",action="store_true"); parser.add_argument("--further-unlikely",action="store_true")
if __name__=="__main__":
 args=parser.parse_args(); catalog={key:set(value) for key,value in json.loads(args.reference_catalog.read_text()).items()}; output=CaseOutput.model_validate_json(args.case_file.read_text()); validate_output(output,CatalogResolver(catalog),stop=StopContext(args.independent_evidence_count,args.verification_settled,args.further_unlikely)); print("valid")
