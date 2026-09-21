"""Grounded value objects shared by GraphRAG ingestion and retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source_type: str
    source_id: str
    title: str
    text: str
    section: str

    def attributes(self) -> dict[str, str]:
        return {"source_type": self.source_type, "source_id": self.source_id,
                "title": self.title, "text": self.text, "section": self.section}


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: KnowledgeChunk
    similarity_score: float | None
    source_reference: str


@dataclass(frozen=True)
class GraphRAGResult:
    graph_evidence: list[dict[str, Any]]
    similar_cases: list[RetrievedChunk]
    pattern_docs: list[RetrievedChunk]
    policy_docs: list[RetrievedChunk]
