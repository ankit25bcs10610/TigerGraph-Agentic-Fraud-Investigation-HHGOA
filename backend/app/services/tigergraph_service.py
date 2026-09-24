"""Read-only TigerGraph service implemented exclusively via MCP tools."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from backend.app.mcp.tigergraph_client import (
    TigerGraphMCPClient,
    TigerGraphMCPGraphNotFoundError,
    TigerGraphMCPMalformedResponseError,
    TigerGraphMCPVertexNotFoundError,
)


class TigerGraphService:
    """Typed application-facing operations over a connected MCP client.

    This class does not know or use TigerGraph REST endpoints.  Each call first
    filters candidate arguments against the live MCP tool schema, which protects
    the integration from drifting server-side parameter definitions.
    """

    def __init__(self, client: TigerGraphMCPClient) -> None:
        self.client = client

    @property
    def graph_name(self) -> str:
        if self.client.config is None:
            raise TigerGraphMCPMalformedResponseError(
                "TigerGraph service requires a connected MCP client configuration."
            )
        return self.client.config.graph_name

    async def list_graphs(self) -> list[str]:
        data = await self._call("tigergraph__list_graphs", {})
        graphs = data.get("graphs")
        if not isinstance(graphs, list) or not all(isinstance(graph, str) for graph in graphs):
            raise TigerGraphMCPMalformedResponseError(
                "list_graphs returned an invalid graphs list."
            )
        return graphs

    async def get_schema(self) -> dict[str, Any]:
        return await self._call("tigergraph__get_graph_schema", {"graph_name": self.graph_name})

    async def get_vertex_count(self, vertex_type: str) -> int:
        data = await self._call(
            "tigergraph__get_vertex_count",
            {"graph_name": self.graph_name, "vertex_type": vertex_type},
        )
        count = data.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise TigerGraphMCPMalformedResponseError(
                f"get_vertex_count returned an invalid count for '{vertex_type}'."
            )
        return count

    async def get_edge_count(self, edge_type: str) -> int:
        data = await self._call(
            "tigergraph__get_edge_count",
            {"graph_name": self.graph_name, "edge_type": edge_type},
        )
        count = data.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise TigerGraphMCPMalformedResponseError(
                f"get_edge_count returned an invalid count for '{edge_type}'."
            )
        return count

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        return await self.get_vertex("Customer", customer_id)

    async def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        return await self.get_vertex("Transaction", transaction_id)

    async def get_vertex(self, vertex_type: str, vertex_id: str) -> dict[str, Any]:
        data = await self._call(
            "tigergraph__get_node",
            {
                "graph_name": self.graph_name,
                "vertex_type": vertex_type,
                "vertex_id": vertex_id,
            },
        )
        if not isinstance(data, dict) or not data:
            raise TigerGraphMCPVertexNotFoundError(
                f"Vertex '{vertex_id}' of type '{vertex_type}' was not found."
            )
        return data

    async def get_neighbors(
        self,
        vertex_type: str,
        vertex_id: str,
        *,
        edge_type: str | None = None,
        target_vertex_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        data = await self._call(
            "tigergraph__get_neighbors",
            {
                "graph_name": self.graph_name,
                "vertex_type": vertex_type,
                "vertex_id": vertex_id,
                "edge_type": edge_type,
                "target_vertex_type": target_vertex_type,
                "limit": limit,
            },
        )
        neighbors = data.get("neighbors")
        count = data.get("count")
        if not isinstance(neighbors, list) or not isinstance(count, int):
            raise TigerGraphMCPMalformedResponseError(
                f"get_neighbors returned an invalid result for '{vertex_id}'."
            )
        return data

    async def list_vertices(self, vertex_type: str, *, limit: int) -> list[dict[str, Any]]:
        """Read vertices through the MCP server; callers choose a safe page size."""
        data = await self._call(
            "tigergraph__get_nodes",
            {"graph_name": self.graph_name, "vertex_type": vertex_type, "limit": limit},
        )
        vertices = data.get("vertices") or data.get("nodes")
        if not isinstance(vertices, list) or not all(isinstance(item, dict) for item in vertices):
            raise TigerGraphMCPMalformedResponseError("get_nodes returned an invalid vertex list.")
        return vertices

    async def list_vector_attributes(self, vertex_type: str) -> dict[str, Any]:
        return await self._call(
            "tigergraph__list_vector_attributes",
            {"graph_name": self.graph_name, "vertex_type": vertex_type},
        )

    async def add_vector_attribute(
        self, *, vertex_type: str, vector_name: str, dimension: int, metric: str
    ) -> dict[str, Any]:
        return await self._call(
            "tigergraph__add_vector_attribute",
            {"graph_name": self.graph_name, "vertex_type": vertex_type,
             "vector_name": vector_name, "dimension": dimension, "metric": metric},
        )

    async def get_vector_index_status(
        self, *, vertex_type: str, vector_name: str
    ) -> dict[str, Any]:
        return await self._call(
            "tigergraph__get_vector_index_status",
            {"graph_name": self.graph_name, "vertex_type": vertex_type, "vector_name": vector_name},
        )

    async def upsert_vectors(
        self, *, vertex_type: str, vector_attribute: str, vectors: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self._call(
            "tigergraph__upsert_vectors",
            {"graph_name": self.graph_name, "vertex_type": vertex_type,
             "vector_attribute": vector_attribute, "vectors": vectors},
        )

    async def add_nodes(self, vertex_type: str, vertices: list[dict[str, Any]], *, vertex_id: str) -> dict[str, Any]:
        return await self._call(
            "tigergraph__add_nodes",
            {"graph_name": self.graph_name, "vertex_type": vertex_type, "vertex_id": vertex_id, "vertices": vertices},
        )

    async def load_vectors_from_json(
        self, *, vertex_type: str, vector_attribute: str, file_path: str,
        id_key: str = "id", vector_key: str = "vector",
    ) -> dict[str, Any]:
        return await self._call(
            "tigergraph__load_vectors_from_json",
            {"graph_name": self.graph_name, "vertex_type": vertex_type,
             "vector_attribute": vector_attribute, "file_path": file_path,
             "id_key": id_key, "vector_key": vector_key},
        )

    async def run_gsql(self, command: str) -> dict[str, Any]:
        return await self._call("tigergraph__gsql", {"command": command})

    async def search_top_k_similarity(
        self, *, vertex_type: str, vector_attribute: str, query_vector: list[float], top_k: int
    ) -> dict[str, Any]:
        return await self._call(
            "tigergraph__search_top_k_similarity",
            {"graph_name": self.graph_name, "vertex_type": vertex_type,
             "vector_attribute": vector_attribute, "query_vector": query_vector, "top_k": top_k},
        )

    async def run_installed_query(
        self, query_name: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run an already-installed GSQL query through the official MCP tool."""
        values = dict(params or {})
        try:
            return await self._call(
                "tigergraph__run_installed_query",
                {
                    "graph_name": self.graph_name,
                    "query_name": query_name,
                    "params": values,
                },
            )
        except Exception as exc:  # noqa: BLE001 - Savanna may expose catalog queries before REST++ routes.
            if "404" not in str(exc):
                raise
            return await self._run_interpreted_query(query_name, values)

    async def _run_interpreted_query(
        self, query_name: str, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        query_data = await self._call(
            "tigergraph__show_query",
            {"graph_name": self.graph_name, "query_name": query_name},
        )
        query_code = query_data.get("query_code")
        if not isinstance(query_code, str):
            raise TigerGraphMCPMalformedResponseError(
                f"show_query returned no source for '{query_name}'."
            )
        source = query_code[query_code.find("CREATE QUERY "):]
        match = re.match(
            r"CREATE QUERY [^(]+\(([^)]*)\) FOR GRAPH [^{]+\{(.*)\}\s*$",
            source,
            re.DOTALL,
        )
        if match is None:
            raise TigerGraphMCPMalformedResponseError(
                f"Cannot convert '{query_name}' to an interpreted query."
            )
        declarations = []
        for declaration in match.group(1).split(","):
            parts = declaration.strip().split()
            if len(parts) != 2 or parts[1] not in params:
                continue
            type_name, parameter = parts
            value = params[parameter]
            if isinstance(value, bool):
                literal = "TRUE" if value else "FALSE"
            elif isinstance(value, (int, float)):
                literal = str(value)
            else:
                literal = json.dumps(str(value))
            declarations.append(f"{type_name} {parameter}={literal}")
        if len(declarations) != len(params):
            raise TigerGraphMCPMalformedResponseError(
                f"Missing typed parameters for interpreted query '{query_name}'."
            )
        query_text = (
            f"INTERPRET QUERY ({', '.join(declarations)}) FOR GRAPH {self.graph_name}"
            f" {{{match.group(2)}}}"
        )
        return await self._call(
            "tigergraph__run_query",
            {"graph_name": self.graph_name, "query_text": query_text},
        )

    async def ensure_graph_exists(self) -> None:
        graphs = await self.list_graphs()
        if self.graph_name not in graphs:
            raise TigerGraphMCPGraphNotFoundError(
                f"TigerGraph graph '{self.graph_name}' was not returned by list_graphs."
            )

    async def _call(
        self, tool_name: str, candidate_values: Mapping[str, Any]
    ) -> dict[str, Any]:
        arguments = await self.client.arguments_for(tool_name, candidate_values)
        payload = await self.client.call_tool(tool_name, arguments)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TigerGraphMCPMalformedResponseError(
                f"TigerGraph MCP tool '{tool_name}' returned no structured data object."
            )
        return data
