"""Conversion of graph facts into grounded answer-format evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from backend.models.answer import Evidence, EvidenceSource


@dataclass(frozen=True)
class GraphEvidence:
    """A fact already returned by a graph query.

    The adapter deliberately does not infer a claim from opaque graph fields;
    the caller must supply the factual claim and the query/entity reference.
    """

    claim: str
    ref: str
    entity_ids: tuple[str, ...]
    source: EvidenceSource = EvidenceSource.GRAPH


def to_answer_evidence(items: Iterable[GraphEvidence]) -> list[Evidence]:
    """Validate and convert grounded graph facts to strict answer evidence."""
    result: list[Evidence] = []
    for item in items:
        claim = item.claim.strip()
        ref = item.ref.strip()
        entity_ids = [entity_id.strip() for entity_id in item.entity_ids if entity_id.strip()]
        if not claim:
            raise ValueError("grounded evidence claim must not be empty")
        if not ref:
            raise ValueError("grounded evidence ref must not be empty")
        if not entity_ids:
            raise ValueError("grounded evidence must include at least one entity id")
        result.append(
            Evidence(
                claim=claim,
                source=item.source,
                ref=ref,
                entity_ids=entity_ids,
            )
        )
    return result


def graph_rows_to_evidence(
    rows: Iterable[Mapping[str, object]],
    *,
    query_ref: str,
    claim_field: str = "claim",
    entity_fields: Sequence[str] = ("transaction_id",),
) -> list[Evidence]:
    """Adapt query rows without inventing facts.

    Each row must contain a non-empty claim and at least one configured entity
    field. Values are stringified only after being read from the row.
    """
    items: list[GraphEvidence] = []
    for row in rows:
        claim = row.get(claim_field)
        if claim is None:
            raise ValueError(f"graph row is missing claim field {claim_field!r}")
        entity_ids = tuple(
            str(row[field])
            for field in entity_fields
            if field in row and row[field] not in (None, "")
        )
        items.append(
            GraphEvidence(
                claim=str(claim),
                ref=query_ref,
                entity_ids=entity_ids,
            )
        )
    return to_answer_evidence(items)

