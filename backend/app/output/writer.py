from __future__ import annotations
import json
from pathlib import Path
from .models import CaseOutput
from .validator import ReferenceResolver, StopContext, validate_output
def write_case_output(output: CaseOutput, directory: Path, resolver: ReferenceResolver, *, stop: StopContext = StopContext()) -> Path:
    validate_output(output, resolver, stop=stop)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{output.case_id}.json"
    target.write_text(json.dumps(output.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return target
