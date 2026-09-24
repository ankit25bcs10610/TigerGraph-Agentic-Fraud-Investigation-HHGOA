"""Hybrid graph and vector retrieval with source references on every result."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from backend.app.rag.embeddings import EmbeddingProvider
from backend.app.rag.ingestion import KNOWLEDGE_VERTEX_TYPE
from backend.app.rag.models import GraphRAGResult, KnowledgeChunk, RetrievedChunk
from backend.app.services.tigergraph_service import TigerGraphService


def _attributes(vertex: dict[str, Any]) -> dict[str, Any]:
    return vertex.get("attributes", {}) if isinstance(vertex.get("attributes"), dict) else vertex


def _id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("v_id", "vertex_id", "id"):
            if value.get(key) is not None:
                return str(value[key])
        for nested in value.values():
            found = _id(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _id(nested)
            if found:
                return found
    return None


class GraphRAGRetriever:
    def __init__(self, service: TigerGraphService, embeddings: EmbeddingProvider, *, vector_attribute: str) -> None:
        self.service, self.embeddings, self.vector_attribute = service, embeddings, vector_attribute

    async def _search(self, query_text: str, source_type: str, top_k: int) -> list[RetrievedChunk]:
        if top_k <= 0:
            return []
        vector = self.embeddings.embed([query_text])[0]
        # Over-fetching prevents one source category from starving another on a shared index.
        results = await self.service.run_installed_query(
            "rag_vector_search", {"query_vector": vector, "top_k": top_k, "source_type": source_type}
        )
        candidates: list[dict[str, Any]] = []
        distances: dict[str, float] = {}
        for block in results.get("result", []):
            if not isinstance(block, dict):
                continue
            values = block.get("result") or block.get("vertices") or block.get("rows") or []
            if isinstance(values, list):
                candidates.extend(item for item in values if isinstance(item, dict))
            raw_distances = block.get("@@distances") or block.get("distances") or {}
            if isinstance(raw_distances, dict):
                distances.update({str(key): float(value) for key, value in raw_distances.items() if isinstance(value, (int, float))})
        retrieved: list[RetrievedChunk] = []
        for candidate in candidates:
            chunk_id = _id(candidate)
            if not chunk_id:
                continue
            vertex = await self.service.get_vertex(KNOWLEDGE_VERTEX_TYPE, chunk_id)
            attrs = _attributes(vertex)
            if attrs.get("source_type") != source_type:
                continue
            try:
                chunk = KnowledgeChunk(chunk_id, str(attrs["source_type"]), str(attrs["source_id"]),
                    str(attrs["title"]), str(attrs["text"]), str(attrs["section"]))
            except KeyError:
                continue
            distance = distances.get(chunk_id)
            score = (1.0 - distance) if distance is not None else candidate.get("score", candidate.get("distance"))
            retrieved.append(RetrievedChunk(chunk, float(score) if isinstance(score, (float, int)) else None,
                f"graph:KnowledgeChunk/{chunk_id}"))
            if len(retrieved) == top_k:
                break
        return retrieved

    async def search_similar_closed_cases(self, query_text: str, top_k: int = 5) -> list[RetrievedChunk]:
        return await self._search(query_text, "closed_case", top_k)

    async def search_policy(self, query_text: str, top_k: int = 5) -> list[RetrievedChunk]:
        return await self._search(query_text, "policy", top_k)

    async def search_patterns(self, query_text: str, top_k: int = 5) -> list[RetrievedChunk]:
        return await self._search(query_text, "pattern_document", top_k)

    async def retrieve_case_context(self, customer_id: str, card_id: str, transaction_id: str) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for kind, task in (("customer", self.service.get_customer(customer_id)),
                           ("card", self.service.get_vertex("Card", card_id)),
                           ("transaction", self.service.get_transaction(transaction_id))):
            vertex = await task
            evidence.append({"source": "graph", "ref": f"get_node:{kind}", "entity_ids": [str(_id(vertex) or "")], "data": vertex})
        for edge, target in (("FROM_DEVICE", "DeviceProfile"), ("PURCHASER_EMAIL", "EmailDomain"), ("BILLED_IN", "BillingRegion")):
            neighbors = await self.service.get_neighbors("Transaction", transaction_id, edge_type=edge, target_vertex_type=target, limit=25)
            evidence.append({"source": "graph", "ref": f"get_neighbors:{edge}", "entity_ids": [transaction_id], "data": neighbors})
        return evidence

    async def hybrid_retrieve(self, query_text: str, customer_id: str | None = None, card_id: str | None = None,
                              transaction_id: str | None = None, top_k: int = 5) -> GraphRAGResult:
        graph_evidence = []
        if customer_id and card_id and transaction_id:
            graph_evidence = await self.retrieve_case_context(customer_id, card_id, transaction_id)
        similar_cases, pattern_docs, policy_docs = await self.search_similar_closed_cases(query_text, top_k), await self.search_patterns(query_text, top_k), await self.search_policy(query_text, top_k)
        return GraphRAGResult(graph_evidence, similar_cases, pattern_docs, policy_docs)
