"""Read-only TigerGraph service implemented exclusively via MCP tools."""

from __future__ import annotations

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

    async def run_installed_query(
        self, query_name: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run an already-installed GSQL query through the official MCP tool."""
        return await self._call(
            "tigergraph__run_installed_query",
            {
                "graph_name": self.graph_name,
                "query_name": query_name,
                "params": dict(params or {}),
            },
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
