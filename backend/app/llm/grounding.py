from __future__ import annotations
import re
from .models import Synthesis
class GroundingError(ValueError): pass
_ID = re.compile(r"\b(?:[A-Za-z]+[-_]?[A-Za-z0-9]+|\d{4,})\b")
def validate_synthesis(synthesis: Synthesis, allowed_references: set[str], allowed_ids: set[str]) -> Synthesis:
    for field, refs in synthesis.citations.items():
        if any(ref not in allowed_references for ref in refs): raise GroundingError(f"unsupported citation in {field}")
    text = " ".join((synthesis.pattern_description, synthesis.evidence_explanation, synthesis.uncertainty_explanation, synthesis.action_explanation, synthesis.case_summary))
    candidates = {token for token in _ID.findall(text) if token.startswith(("C", "CC", "HHG", "D", "T")) or token.isdigit()}
    if candidates - allowed_ids: raise GroundingError("synthesis referenced unsupported entity IDs")
    return synthesis
