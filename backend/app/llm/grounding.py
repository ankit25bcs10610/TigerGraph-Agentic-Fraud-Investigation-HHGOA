from __future__ import annotations
import re
from .models import Synthesis
class GroundingError(ValueError): pass
# An identifier-like token: letters/digits joined by - or _, containing at least one digit
# (C12382-K1, 3514030, SMP-T2005, CC-501). Ordinary words are never treated as IDs.
_ID = re.compile(r"\b[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*\b")


def id_tokens(text: str) -> set[str]:
    return {token for token in _ID.findall(text) if any(char.isdigit() for char in token) and len(token) >= 4}
def validate_synthesis(synthesis: Synthesis, allowed_references: set[str], allowed_ids: set[str]) -> Synthesis:
    for field, refs in synthesis.citations.items():
        if any(ref not in allowed_references for ref in refs): raise GroundingError(f"unsupported citation in {field}")
    text = " ".join((synthesis.pattern_description, synthesis.evidence_explanation, synthesis.uncertainty_explanation, synthesis.action_explanation, synthesis.case_summary))
    candidates = id_tokens(text)
    if candidates - allowed_ids: raise GroundingError("synthesis referenced unsupported entity IDs")
    return synthesis
