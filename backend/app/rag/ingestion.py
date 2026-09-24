"""Repeatable, MCP-backed ingestion of factual GraphRAG knowledge."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.rag.embeddings import EmbeddingProvider
from backend.app.rag.models import KnowledgeChunk
from backend.app.services.tigergraph_service import TigerGraphService


KNOWLEDGE_VERTEX_TYPE = os.getenv("GRAPHRAG_VERTEX_TYPE", "KnowledgeChunk").strip() or "KnowledgeChunk"


def _value(vertex: dict[str, Any], name: str) -> Any:
    attributes = vertex.get("attributes", {})
    return attributes.get(name, vertex.get(name, "")) if isinstance(attributes, dict) else vertex.get(name, "")


def _vertex_id(vertex: dict[str, Any]) -> str:
    value = vertex.get("v_id", vertex.get("vertex_id", vertex.get("id", "")))
    return str(value).strip()


def _chunk_id(source_type: str, source_id: str, section: str, text: str) -> str:
    payload = "\x1f".join((source_type, source_id, section, text)).encode("utf-8")
    return "kc-" + hashlib.sha256(payload).hexdigest()


def _chunk(source_type: str, source_id: str, title: str, text: str, section: str) -> KnowledgeChunk:
    cleaned = " ".join(text.split())
    return KnowledgeChunk(_chunk_id(source_type, source_id, section, cleaned), source_type, source_id, title, cleaned, section)


def closed_case_chunks(vertices: Iterable[dict[str, Any]]) -> list[KnowledgeChunk]:
    """Build retrieval text only from factual ClosedCase graph attributes."""
    documents: list[KnowledgeChunk] = []
    for vertex in vertices:
        case_id = _vertex_id(vertex)
        if not case_id:
            continue
        fields = {name: _value(vertex, name) for name in (
            "outcome", "pattern", "exposure_usd", "actions_taken", "analyst_notes", "first_fraud_txn_id"
        )}
        text = "\n".join((
            f"Case: {case_id}", f"Outcome: {fields['outcome']}", f"Pattern: {fields['pattern']}",
            f"Exposure USD: {fields['exposure_usd']}", f"Actions taken: {fields['actions_taken']}",
            f"First fraud transaction: {fields['first_fraud_txn_id']}", f"Analyst notes: {fields['analyst_notes']}",
        ))
        documents.append(_chunk("closed_case", case_id, f"Closed case {case_id}", text, "historical investigation"))
    return documents


def _markdown_sections(markdown: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^(#{1,4})\s+(.+?)\s*$", markdown, flags=re.MULTILINE))
    return [(match.group(2).strip(), markdown[match.end(): matches[index + 1].start() if index + 1 < len(matches) else len(markdown)].strip()) for index, match in enumerate(matches)]


def _split_long(chunk: KnowledgeChunk, max_characters: int) -> list[KnowledgeChunk]:
    if max_characters <= 0 or len(chunk.text) <= max_characters:
        return [chunk]
    parts = [chunk.text[index:index + max_characters] for index in range(0, len(chunk.text), max_characters)]
    return [_chunk(chunk.source_type, chunk.source_id, chunk.title, part, f"{chunk.section} part {index + 1}") for index, part in enumerate(parts)]


def readme_chunks(readme_path: Path, *, max_characters: int) -> list[KnowledgeChunk]:
    """Extract pattern, policy, approval, case/report, and stopping material from README."""
    markdown = readme_path.read_text(encoding="utf-8")
    chunks: list[KnowledgeChunk] = []
    for heading, text in _markdown_sections(markdown):
        lower = heading.lower()
        source_type = ""
        source_id = ""
        if "known fraud patterns" in lower:
            source_type, source_id = "pattern_document", "known_patterns"
        elif re.fullmatch(r"[rR]\d+\.?.*", heading):
            source_type, source_id = "policy", heading.split(".", 1)[0].upper()
        elif any(term in lower for term in ("approval routing", "a case is not a report", "next best action", "stopping")):
            source_type, source_id = "policy", re.sub(r"[^a-z0-9]+", "_", lower).strip("_")
        if source_type and text:
            chunks.extend(_split_long(_chunk(source_type, source_id, heading, text, heading), max_characters))
    return chunks


@dataclass
class GraphRAGIngestor:
    service: TigerGraphService
    embeddings: EmbeddingProvider
    vector_attribute: str
    metric: str = "COSINE"
    batch_size: int = 64

    async def ensure_vector_schema(self) -> None:
        """Create the local vector attribute and installed search query if needed."""
        graph_name = self.service.graph_name
        job_name = "add_graphrag_vector"
        command = f'''USE GRAPH {graph_name}
CREATE SCHEMA_CHANGE JOB {job_name} FOR GRAPH {graph_name} {{
  ALTER VERTEX {KNOWLEDGE_VERTEX_TYPE} ADD VECTOR ATTRIBUTE {self.vector_attribute}(DIMENSION={self.embeddings.dimension}, METRIC="{self.metric}");
}}
RUN SCHEMA_CHANGE JOB {job_name}'''
        try:
            await self.service.run_gsql(command)
        except Exception as error:  # noqa: BLE001 - an existing vector is idempotent.
            message = str(error).lower()
            if "conflict" not in message and "already" not in message and "used by another" not in message:
                raise
        query = f'''USE GRAPH {graph_name}
CREATE OR REPLACE QUERY rag_vector_search(LIST<FLOAT> query_vector, INT top_k, STRING source_type) FOR GRAPH {graph_name} SYNTAX v3 {{
  MapAccum<Vertex, FLOAT> @@distances;
  candidates = SELECT k FROM {KNOWLEDGE_VERTEX_TYPE}:k WHERE k.source_type == source_type;
  result = vectorSearch({{{KNOWLEDGE_VERTEX_TYPE}.{self.vector_attribute}}}, query_vector, top_k, {{candidate_set: candidates, distance_map: @@distances}});
  PRINT result WITH VECTOR;
  PRINT @@distances;
}}
INSTALL QUERY rag_vector_search'''
        await self.service.run_gsql(query)

    async def ingest(self, *, readme_path: Path, closed_case_limit: int, max_characters: int) -> dict[str, int]:
        vertices = await self.service.list_vertices("ClosedCase", limit=closed_case_limit)
        chunks = closed_case_chunks(vertices) + readme_chunks(readme_path, max_characters=max_characters)
        if not chunks:
            return {"closed_case": 0, "pattern_document": 0, "policy": 0, "total": 0}
        vectors = self.embeddings.embed([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("Embedding provider returned a different number of vectors than chunks.")
        await self.ensure_vector_schema()
        if hasattr(self.service, "add_nodes") and hasattr(self.service, "load_vectors_from_json"):
            for start in range(0, len(chunks), self.batch_size * 8):
                batch = chunks[start:start + self.batch_size * 8]
                await self.service.add_nodes(
                    KNOWLEDGE_VERTEX_TYPE,
                    [{"chunk_id": item.chunk_id, **item.attributes()} for item in batch],
                    vertex_id="chunk_id",
                )
            with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8", delete=False) as handle:
                vector_file = handle.name
                for chunk, vector in zip(chunks, vectors, strict=True):
                    handle.write(json.dumps({"id": chunk.chunk_id, "vector": ",".join(str(value) for value in vector)}) + "\n")
            try:
                await self.service.load_vectors_from_json(
                    vertex_type=KNOWLEDGE_VERTEX_TYPE, vector_attribute=self.vector_attribute,
                    file_path=vector_file, id_key="id", vector_key="vector",
                )
            finally:
                Path(vector_file).unlink(missing_ok=True)
        else:
            for start in range(0, len(chunks), self.batch_size):
                batch_chunks, batch_vectors = chunks[start:start + self.batch_size], vectors[start:start + self.batch_size]
                await self.service.upsert_vectors(vertex_type=KNOWLEDGE_VERTEX_TYPE, vector_attribute=self.vector_attribute,
                    vectors=[{"vertex_id": item.chunk_id, "vector": vector, "attributes": item.attributes()} for item, vector in zip(batch_chunks, batch_vectors, strict=True)])
        counts = {source_type: sum(chunk.source_type == source_type for chunk in chunks) for source_type in ("closed_case", "pattern_document", "policy")}
        return {**counts, "total": len(chunks)}
