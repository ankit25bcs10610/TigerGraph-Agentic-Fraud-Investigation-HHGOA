# GraphRAG retrieval

GraphRAG keeps TigerGraph as both the graph database and vector store. It uses
only the official `tigergraph-mcp` stdio integration; no second vector database
or direct TigerGraph HTTP client is introduced.

## Schema migration

Apply `tigergraph/graphrag_schema.gsql` once to create `KnowledgeChunk`. It
does not alter fraud vertices. The vector attribute is then created through
the MCP `tigergraph__add_vector_attribute` tool after embeddings are generated,
so its dimension comes from the selected provider rather than source code.

`KnowledgeChunk` stores `source_type`, `source_id`, `title`, `text`, and
`section`; its primary ID is a SHA-256 digest of that factual source content.
Repeated ingestion therefore upserts the same chunks rather than duplicating
them.

## Configuration

Set TigerGraph MCP configuration as documented in `TIGERGRAPH_MCP.md`, then
select an embedding provider without committing any key:

```dotenv
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=<sentence-transformers model name>
# Or: EMBEDDING_PROVIDER=openai and OPENAI_API_KEY=<local secret>
GRAPHRAG_VECTOR_ATTRIBUTE=embedding
```

The local provider loads `sentence-transformers` lazily. The OpenAI provider
loads `openai` lazily and requires `OPENAI_API_KEY`; neither key nor vectors
are logged by the application.

## Ingest

Provide the actual README and an explicit ClosedCase retrieval limit:

```bash
python scripts/index_fraud_knowledge.py \
  --readme /path/to/README.md --closed-case-limit <number-in-graph>
```

The pipeline reads `ClosedCase` vertices through MCP, creates factual text
from the case attributes, extracts README pattern/policy/approval/case/report
and stopping sections, embeds the chunks, and upserts them through
`tigergraph__upsert_vectors`. It never reads `case_pack` outcomes or public
IEEE/Kaggle fraud labels.

## Retrieve

```bash
python scripts/test_graphrag.py \
  --query "review the alert" --customer-id C12382 \
  --card-id C12382-K1 --transaction-id 3514030
```

This is read-only and returns graph evidence plus source-referenced similar
closed cases, pattern documents, and policy documents. Similarity is evidence,
not a fraud verdict. The caller must still confirm that an inferred decision is
supported by graph evidence and policy.

## Validation

Before operational use, use MCP to verify the vector attribute, its reported
dimension, and `get_vector_index_status` is ready. Then run the retrieval smoke
test against a credentialed graph and confirm every returned `closed_case`
source ID resolves to an existing `ClosedCase` vertex. No live validation can
be claimed without the configured TigerGraph and embedding credentials.
