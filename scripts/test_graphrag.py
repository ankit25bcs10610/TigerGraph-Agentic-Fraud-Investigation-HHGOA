#!/usr/bin/env python3
"""Read-only GraphRAG retrieval smoke test; IDs are explicit command arguments."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from backend.app.mcp.tigergraph_client import TigerGraphMCPClient, TigerGraphMCPConfig
from backend.app.rag.embeddings import EmbeddingSettings, create_embedding_provider
from backend.app.rag.retriever import GraphRAGRetriever
from backend.app.services.tigergraph_service import TigerGraphService

def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--customer-id", required=True)
    parser.add_argument("--card-id", required=True)
    parser.add_argument("--transaction-id", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()

async def run(options: argparse.Namespace) -> dict:
    vector_name = os.environ.get("GRAPHRAG_VECTOR_ATTRIBUTE", "local_embedding").strip()
    async with TigerGraphMCPClient(TigerGraphMCPConfig.from_environment()) as client:
        retriever = GraphRAGRetriever(TigerGraphService(client), create_embedding_provider(EmbeddingSettings.from_environment()), vector_attribute=vector_name)
        result = await retriever.hybrid_retrieve(options.query, options.customer_id, options.card_id, options.transaction_id, options.top_k)
        return {"graph_evidence": result.graph_evidence, "similar_cases": [item.__dict__ for item in result.similar_cases], "pattern_docs": [item.__dict__ for item in result.pattern_docs], "policy_docs": [item.__dict__ for item in result.policy_docs]}

if __name__ == "__main__": print(json.dumps(asyncio.run(run(args())), indent=2, default=str))
