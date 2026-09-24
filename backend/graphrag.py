"""GraphRAG for the agent: retrieve the policy passages and prior-case narratives
that matter for *this* investigation, and hand only those to the explanation.

Two retrievers, one contract:

* ``TigerGraphVectorRAG`` embeds the case query and runs top-k vector search
  over ``KnowledgeChunk`` vertices through TigerGraph MCP (the production
  path; chunks are ingested by ``scripts/index_fraud_knowledge.py``).
* ``LocalSemanticRAG`` ranks the same kinds of passages with TF-IDF cosine
  similarity when no vector index is available.

Every passage carries its source reference and the method that found it, so
the UI and the answer files can say exactly where grounding came from.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from backend.policy.knowledge import PolicyKnowledge
from backend.sources.base import ClosedCaseRecord


@dataclass(frozen=True)
class Passage:
    ref: str
    kind: str          # "policy" | "closed_case" | "pattern_document"
    title: str
    text: str
    source_id: str
    score: float
    method: str        # "tigergraph-vector" | "tfidf"


def case_narrative(case: ClosedCaseRecord) -> str:
    return " ".join(filter(None, [f"{case.outcome.replace('_', ' ')} case", f"pattern {case.pattern.replace('_', ' ')}", case.analyst_notes]))


_WORD = re.compile(r"[a-z0-9$]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "be", "with", "by", "if", "as", "at", "it", "that", "this", "from", "was", "were"}


def _terms(text: str) -> list[str]:
    words = [word for word in _WORD.findall(text.lower()) if word not in _STOP and len(word) > 1]
    return words + [f"{a} {b}" for a, b in zip(words, words[1:])]  # unigrams and bigrams


class LocalSemanticRAG:
    """TF-IDF cosine retrieval (sublinear term frequency, unigrams and bigrams), no dependencies."""

    method = "tfidf"

    def __init__(self, knowledge: PolicyKnowledge, closed_cases: Iterable[ClosedCaseRecord] = ()) -> None:
        self._passages: list[Passage] = []
        for chunk in knowledge.chunks:
            kind = "pattern_document" if "pattern" in chunk.source.lower() else "policy"
            self._passages.append(Passage(chunk.ref, kind, chunk.title, chunk.text, chunk.ref, 0.0, self.method))
        for case in closed_cases:
            narrative = case_narrative(case)
            if narrative.strip():
                self._passages.append(Passage(f"closed_case:{case.case_id}", "closed_case", case.case_id, narrative, case.case_id, 0.0, self.method))
        counts = [Counter(_terms(f"{item.title} {item.text}")) for item in self._passages]
        documents = max(1, len(counts))
        seen = Counter(term for count in counts for term in count)
        self._idf = {term: math.log((1 + documents) / (1 + frequency)) + 1 for term, frequency in seen.items()}
        self._vectors = [self._weigh(count) for count in counts]

    def _weigh(self, counts: Counter[str]) -> dict[str, float]:
        vector = {term: (1 + math.log(count)) * self._idf.get(term, 0.0) for term, count in counts.items() if term in self._idf}
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        return {term: value / norm for term, value in vector.items()}

    def retrieve(self, query: str, kind: str, top_k: int) -> list[Passage]:
        query_vector = self._weigh(Counter(_terms(query)))
        if not query_vector:
            return []
        scored = []
        for passage, vector in zip(self._passages, self._vectors):
            if passage.kind != kind:
                continue
            score = sum(weight * vector.get(term, 0.0) for term, weight in query_vector.items())
            if score > 0:
                scored.append((score, passage))
        scored.sort(key=lambda item: -item[0])
        return [Passage(**{**passage.__dict__, "score": round(score, 3)}) for score, passage in scored[:top_k]]


class TigerGraphVectorRAG:
    method = "tigergraph-vector"

    def __init__(self, source: Any, knowledge: PolicyKnowledge) -> None:
        from backend.app.rag.embeddings import EmbeddingSettings, create_embedding_provider
        from backend.app.rag.retriever import GraphRAGRetriever

        self.source = source
        self.fallback = LocalSemanticRAG(knowledge, getattr(source, "_closed", ()))
        self._vector_available = True
        self.retriever = GraphRAGRetriever(source.service, create_embedding_provider(EmbeddingSettings.from_environment()),
                                           vector_attribute=os.getenv("GRAPHRAG_VECTOR_ATTRIBUTE", "local_embedding"))

    def retrieve(self, query: str, kind: str, top_k: int) -> list[Passage]:
        search = {"policy": self.retriever.search_policy, "closed_case": self.retriever.search_similar_closed_cases,
                  "pattern_document": self.retriever.search_patterns}[kind]
        if not self._vector_available:
            return self.fallback.retrieve(query, kind, top_k)
        try:
            chunks = self.source._loop.run(search(query, top_k), 60)
        except Exception:  # noqa: BLE001 - keep investigations grounded when vector REST++ is unavailable.
            self._vector_available = False
            return self.fallback.retrieve(query, kind, top_k)
        return [Passage(item.source_reference, kind, item.chunk.title, item.chunk.text, item.chunk.source_id, round(item.similarity_score or 0.0, 3), self.method) for item in chunks]


def open_graphrag(source: Any, knowledge: PolicyKnowledge) -> Any:
    """Vector GraphRAG on TigerGraph when embeddings are configured, TF-IDF otherwise."""
    if getattr(source, "name", "") == "tigergraph-mcp" and os.getenv("EMBEDDING_PROVIDER"):
        try:
            return TigerGraphVectorRAG(source, knowledge)
        except Exception:  # noqa: BLE001 - fall back to local retrieval rather than failing the case
            pass
    return LocalSemanticRAG(knowledge, getattr(source, "_closed", ()))
