#!/usr/bin/env python3
"""Index factual closed cases and README knowledge into TigerGraph vectors."""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.mcp.tigergraph_client import TigerGraphMCPClient, TigerGraphMCPConfig
from backend.app.rag.embeddings import EmbeddingSettings, create_embedding_provider
from backend.app.rag.ingestion import GraphRAGIngestor
from backend.app.services.tigergraph_service import TigerGraphService

def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, required=True)
    parser.add_argument("--closed-case-limit", type=int, required=True)
    parser.add_argument("--max-characters", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--metric", default="COSINE")
    return parser.parse_args()

async def main_async(options: argparse.Namespace) -> dict[str, int]:
    settings = EmbeddingSettings.from_environment()
    provider = create_embedding_provider(settings)
    vector_name = __import__("os").environ.get("GRAPHRAG_VECTOR_ATTRIBUTE", "embedding").strip()
    if not vector_name:
        raise ValueError("GRAPHRAG_VECTOR_ATTRIBUTE must not be empty.")
    async with TigerGraphMCPClient(TigerGraphMCPConfig.from_environment()) as client:
        ingestor = GraphRAGIngestor(TigerGraphService(client), provider, vector_name, options.metric, options.batch_size)
        return await ingestor.ingest(readme_path=options.readme, closed_case_limit=options.closed_case_limit, max_characters=options.max_characters)

if __name__ == "__main__":
    print(json.dumps(asyncio.run(main_async(args())), indent=2, sort_keys=True))
