# TigerGraph MCP integration

## Purpose

The backend uses TigerGraph only through the official `tigergraph-mcp` server
over stdio. `backend/app/mcp/tigergraph_client.py` owns an MCP session and
`backend/app/services/tigergraph_service.py` exposes read-only operations for
the application. This keeps graph access typed, inspectable, and separate from
future investigation orchestration.

The integration does not use direct HTTP requests, `pyTigerGraph`, raw REST
calls, LangGraph, or an LLM. `langchain-mcp-adapters` is intentionally not a
dependency yet: the repository has no LangChain/LangGraph integration and this
MCP boundary can be reused directly when one is introduced later.

## Install

Use Python 3.10 or later. From the project root:

```bash
python3 -m pip install -r requirements.txt
```

`requirements.txt` installs the official server package (`tigergraph-mcp`),
the MCP Python SDK, and `python-dotenv` for local configuration.

## Configuration

Copy the example file and add credentials only to the untracked `.env` file:

```bash
cp .env.example .env
```

Required configuration:

```dotenv
TG_HOST=
TG_GRAPHNAME=FraudInvestigationGraph
TG_API_TOKEN=
TG_TGCLOUD=true
TG_SSL_PORT=443
```

Alternatively, supply all of `TG_USERNAME` and `TG_PASSWORD`; `TG_SECRET` is
optional. If both authentication mechanisms are configured, `TG_API_TOKEN`
takes priority. The client reads `.env` with `python-dotenv`, gives explicitly
set environment variables precedence, and passes the resulting `TG_*` values
explicitly to the stdio child process. `.env` is ignored by Git and no code
logs its credential values.

## Standard stdio flow

Application code should reuse one client context for related work:

```python
from backend.app.mcp.tigergraph_client import TigerGraphMCPClient
from backend.app.services.tigergraph_service import TigerGraphService

async with TigerGraphMCPClient() as client:
    service = TigerGraphService(client)
    customer = await service.get_customer("C12382")
```

The client calls `list_tools` first and filters each request through the live
tool's advertised input schema before invoking it. The service supports:

- graph schema and per-type counts;
- customer, transaction, and generic vertex retrieval;
- filtered neighbor traversal; and
- invocation of already-installed GSQL queries.

It does not create or alter schema, load data, install queries, or determine
fraud outcomes.

## Manual server diagnostics

The client normally starts `tigergraph-mcp` automatically. To inspect server
startup manually, use the same shell that contains your `TG_*` configuration:

```bash
tigergraph-mcp -vv
```

Verbose mode is useful when diagnosing installation or stdio startup. Do not
paste the resulting environment values or logs containing credentials into
source control.

## Real read-only smoke test

With valid local credentials, run:

```bash
python scripts/test_tigergraph_mcp.py
```

The script starts the official server through stdio, lists the actual tool
names, confirms `FraudInvestigationGraph` appears in `list_graphs`, verifies
the expected vertex/edge schema names (including lowercase `made`), compares
the validated per-type vertex and edge counts, and retrieves these known graph
records and paths:

- `Customer` `C12382`;
- `C12382 --OWNS--> C12382-K1 --made--> Transaction`;
- `Transaction` `3514030`; and
- available `FROM_DEVICE`, `PURCHASER_EMAIL`, and `BILLED_IN` neighbors for
  that transaction.

It prints only MCP tool names and graph data returned by the server. It makes
no fraud conclusion and makes no mutation. A missing `.env` or credentials is
reported as a configuration error rather than treated as a successful test.

The credential-gated integration suite can also be run explicitly:

```bash
pytest -m integration
```

## Troubleshooting

| Symptom | Likely cause and action |
| --- | --- |
| `tigergraph-mcp command was not found` | Install `requirements.txt` into the Python environment running the smoke command. |
| Connection refused or startup timeout | Check `TG_HOST`, `TG_TGCLOUD=true`, `TG_SSL_PORT=443`, network access, and run `tigergraph-mcp -vv`. |
| Authentication failed | Set `TG_API_TOKEN`, or set both `TG_USERNAME` and `TG_PASSWORD`. Verify the chosen credential has access to the target graph. |
| Graph not found | Ensure `TG_GRAPHNAME=FraudInvestigationGraph` and that the credential can list this graph. |
| Required tool missing | Upgrade/reinstall `tigergraph-mcp`; the client refuses to make an unverified call. |
| Vertex not found | Verify the supplied vertex type and ID against the loaded graph; this is not silently converted to an empty result. |

## Future orchestration boundary

A future LangGraph or agent layer should call `TigerGraphService` or a scoped
adapter around it. It must not bypass this client with direct TigerGraph HTTP
calls. Tool outputs remain deterministic graph evidence; any future LLM may
summarize that evidence but must not replace graph retrieval or query logic.
