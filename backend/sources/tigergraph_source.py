"""Answer the agent's graph questions with installed GSQL queries over TigerGraph MCP.

One MCP session (the official ``tigergraph-mcp`` stdio server) is kept open on
a background event loop, so the synchronous agent can call graph tools
without re-spawning the server for every question.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping

from backend.sources.base import (BURST_MIN_CUSTOMERS, BURST_SPAN_HOURS, COMMON_DEVICE_CUSTOMERS, RING_MAX_CARDS, RING_WINDOW,
                                  ClosedCaseRecord, Community, RingResult, Txn, clean, parse_float, parse_time)

QUERIES = {
    "transaction": "agent_txn_profile",
    "customer": "agent_customer_activity",
    "device": "agent_device_activity",
    "linked_cases": "agent_linked_closed_cases",
    "pattern_cases": "agent_closed_cases_by_pattern",
    "ring": "agent_device_ring",
    "communities": "agent_fraud_communities",
}


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Collect projected rows from a TigerGraph query response, whatever the wrapper."""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("rows"), list):
                for item in node["rows"]:
                    if isinstance(item, dict):
                        found.append(item.get("attributes", item) if isinstance(item.get("attributes"), dict) else item)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def _first(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = _first(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _first(value, key)
            if found is not None:
                return found
    return None


def _one(value: Any) -> str | None:
    """Vertex accumulators print as lists of primary IDs; a transaction has at most one of each."""
    if isinstance(value, (list, tuple, set)):
        return clean(sorted(str(item) for item in value)[0]) if value else None
    return clean(value)


def _txn(row: Mapping[str, Any], device_profile_id: str | None = None) -> Txn | None:
    stamp, amount = parse_time(row.get("ts")), parse_float(row.get("amount"))
    if not row.get("transaction_id") or stamp is None or amount is None:
        return None
    users = row.get("device_customers")
    return Txn(
        transaction_id=str(row["transaction_id"]), customer_id=str(row.get("customer_id") or ""), card_id=str(row.get("card_id") or ""),
        ts=stamp, amount=abs(amount), channel=str(row.get("channel") or ""), risk_score=parse_float(row.get("risk_score")),
        region=_one(row.get("region")), email=_one(row.get("email")), product_code=clean(row.get("product_code")),
        device_profile_id=device_profile_id or _one(row.get("device_profile_id")), device_status=clean(row.get("device_status")),
        proxy_type=clean(row.get("proxy_type")), match_status=clean(row.get("match_status")),
        device_customers=int(users) if users not in (None, "") else None, device_info=clean(row.get("device_info")),
    )


def _split(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return tuple(item.strip() for item in str(value or "").split("|") if item.strip())


def _case(row: Mapping[str, Any]) -> ClosedCaseRecord:
    return ClosedCaseRecord(
        case_id=str(row.get("case_id")), customer_id=str(row.get("customer_id") or ""), card_id=str(row.get("card_id") or ""),
        outcome=str(row.get("outcome") or ""), pattern=str(row.get("pattern") or ""), txn_ids=_split(row.get("txn_ids")),
        connected_card_ids=_split(row.get("connected_card_ids")), exposure_usd=parse_float(row.get("exposure_usd")),
        analyst_notes=str(row.get("analyst_notes") or ""), opened_at=str(row.get("opened_at") or ""),
    )


class _LoopThread:
    """A private event loop that owns the MCP session for its whole life."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="tigergraph-mcp", daemon=True)
        self.thread.start()

    def run(self, coroutine: Any, timeout: float) -> Any:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)


TRANSIENT = ("cannot connect to host", "name or service not known", "no address associated", "temporary failure in name resolution",
             "connection reset", "timed out", "timeout", "server disconnected", "bad gateway", "service unavailable")
RETRY_DELAYS_S = (2.0, 5.0, 12.0)


def _transient(error: Exception) -> bool:
    text = str(error).lower()
    return isinstance(error, (TimeoutError, ConnectionError)) or any(marker in text for marker in TRANSIENT)


class TigerGraphSource:
    name = "tigergraph-mcp"

    def __init__(self, service: Any = None, *, timeout_s: float = 60.0) -> None:
        self._timeout = timeout_s
        self._loop = _LoopThread()
        if service is None:
            from backend.app.mcp.tigergraph_client import TigerGraphMCPClient
            from backend.app.services.tigergraph_service import TigerGraphService

            client = TigerGraphMCPClient()
            self._loop.run(client.connect(), timeout_s)
            service = TigerGraphService(client)
        self.service = service
        self._cache: dict[tuple[str, tuple[tuple[str, Any], ...]], Any] = {}

    def _with_retries(self, make: Any) -> Any:
        """Run a graph call, retrying transient network failures (DNS, resets, timeouts) with backoff."""
        for delay in (*RETRY_DELAYS_S, None):
            try:
                return self._loop.run(make(), self._timeout)
            except Exception as error:  # noqa: BLE001 - only transient errors are retried
                if delay is None or not _transient(error):
                    raise
                time.sleep(delay)
        return None

    def query(self, name: str, params: Mapping[str, Any]) -> Any:
        key = (name, tuple(sorted(params.items())))
        if key not in self._cache:
            self._cache[key] = self._with_retries(lambda: self.service.run_installed_query(name, dict(params)))
        return self._cache[key]

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        """Call any MCP tool (used by the graph writer)."""
        async def invoke() -> Any:
            client = self.service.client
            prepared = await client.arguments_for(tool_name, arguments)
            return await client.call_tool(tool_name, prepared)
        return self._with_retries(invoke)

    # --------------------------------------------------------------- tools

    def transaction(self, transaction_id: str) -> Txn | None:
        rows = [_txn(row) for row in _rows(self.query(QUERIES["transaction"], {"transaction_id": transaction_id}))]
        return next((row for row in rows if row), None)

    def _txns(self, payload: Any) -> list[Txn]:
        return sorted((row for row in map(_txn, _rows(payload)) if row), key=lambda item: (item.ts, item.transaction_id))

    def customer_transactions(self, customer_id: str) -> list[Txn]:
        return self._txns(self.query(QUERIES["customer"], {"customer_id": customer_id}))

    def device_transactions(self, device_profile_id: str) -> list[Txn]:
        payload = self.query(QUERIES["device"], {"device_profile_id": device_profile_id})
        users = _first(payload, "device_customers")
        rows = (_txn({**row, "device_customers": users}, device_profile_id) for row in _rows(payload))
        return sorted((row for row in rows if row), key=lambda item: (item.ts, item.transaction_id))

    def linked_closed_cases(self, customer_id: str, card_id: str, related_customers: set[str], related_txns: set[str]) -> list[ClosedCaseRecord]:
        cases = {case.case_id: case for case in map(_case, _rows(self.query(QUERIES["linked_cases"], {"customer_id": customer_id, "card_id": card_id})))}
        for other in sorted(item for item in related_customers - {customer_id} if item)[:10]:
            for case in map(_case, _rows(self.query(QUERIES["linked_cases"], {"customer_id": other, "card_id": ""}))):
                cases.setdefault(case.case_id, case)
        return list(cases.values())

    def closed_cases_by_pattern(self, pattern: str, limit: int) -> list[ClosedCaseRecord]:
        return [_case(row) for row in _rows(self.query(QUERIES["pattern_cases"], {"pattern": pattern, "k": limit}))]

    def device_ring(self, device_profile_id: str, max_hops: int, around: datetime | None = None) -> RingResult:
        start, end = (around - RING_WINDOW, around + RING_WINDOW) if around else (datetime(1970, 1, 1), datetime(2100, 1, 1))
        payload = self.query(QUERIES["ring"], {"device_profile_id": device_profile_id, "max_hops": max_hops, "max_device_customers": COMMON_DEVICE_CUSTOMERS,
                                               "max_cards": RING_MAX_CARDS, "from_ts": start.strftime("%Y-%m-%d %H:%M:%S"), "to_ts": end.strftime("%Y-%m-%d %H:%M:%S")})
        values = lambda key: tuple(sorted(str(item) for item in (_first(payload, key) or [])))  # noqa: E731
        return RingResult(device_profile_id, values("devices"), values("cards"), values("customers"), int(_first(payload, "transactions") or 0), values("confirmed_cases"),
                          int(_first(payload, "hops") or 0), {"common_devices_skipped": len(_first(payload, "common_devices_skipped") or [])})

    def communities(self, min_customers: int, top_k: int) -> list[Community]:
        payload = self.query(QUERIES["communities"], {"min_customers": min_customers, "max_iterations": 20, "top_k": top_k, "min_device_customers": BURST_MIN_CUSTOMERS,
                                                      "max_device_customers": COMMON_DEVICE_CUSTOMERS, "max_span_hours": BURST_SPAN_HOURS})
        members = lambda key, community: tuple(sorted(str(item) for item in ((_first(payload, key) or {}).get(str(community)) or (_first(payload, key) or {}).get(community) or [])))  # noqa: E731
        found = []
        for row in _first(payload, "communities") or []:
            community = row.get("community")
            found.append(Community(str(community), members("cards", community), members("devices", community), (), members("confirmed_cases", community), 0, int(row.get("customers") or 0)))
        return found

    def exists(self, entity_type: str, entity_id: str) -> bool:
        try:
            self._loop.run(self.service.get_vertex(entity_type, entity_id), self._timeout)
            return True
        except Exception:  # noqa: BLE001 - any lookup failure means "not verifiable"
            return False


class MCPGraphWriter:
    """Writes InvestigationCase vertices and edges through TigerGraph MCP tools.

    If the connected MCP server does not advertise a node/edge write tool, the
    writer falls back to pyTigerGraph with the same ``TG_*`` credentials.
    """

    def __init__(self, source: TigerGraphSource, graph_name: str | None = None) -> None:
        self.source = source
        self.graph_name = graph_name or source.service.graph_name
        self._fallback: Any = None

    def _rest(self) -> Any:
        if self._fallback is None:
            from backend.cases.service import PyTigerGraphWriter
            from scripts.setup_tigergraph import connect
            self._fallback = PyTigerGraphWriter(connect())
        return self._fallback

    def upsert_vertex(self, vertex_type: str, vertex_id: str, attributes: Mapping[str, Any]) -> None:
        try:
            self._mcp_vertex(vertex_type, vertex_id, attributes)
        except Exception:  # noqa: BLE001 - optional compatibility fallback
            if not self._rest_fallback_enabled():
                raise
            self._rest().upsert_vertex(vertex_type, vertex_id, attributes)

    def upsert_edge(self, source_vertex_type: str, source_vertex_id: str, edge_type: str, target_vertex_type: str, target_vertex_id: str, attributes: Mapping[str, Any] | None = None) -> None:
        try:
            self._mcp_edge(source_vertex_type, source_vertex_id, edge_type, target_vertex_type, target_vertex_id, attributes)
        except Exception:  # noqa: BLE001
            if not self._rest_fallback_enabled():
                raise
            self._rest().upsert_edge(source_vertex_type, source_vertex_id, edge_type, target_vertex_type, target_vertex_id, attributes)

    def upsert_edges(self, edges: Iterable[tuple[str, str, str, str, str, Mapping[str, Any] | None]]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        types: dict[str, tuple[str, str]] = {}
        for source_type, source_id, edge_type, target_type, target_id, attributes in edges:
            types.setdefault(edge_type, (source_type, target_type))
            source_type_for_edge, target_type_for_edge = types[edge_type]
            if (source_type, target_type) != (source_type_for_edge, target_type_for_edge):
                raise ValueError(f"MCP batch edge types must share endpoints for {edge_type}")
            grouped[edge_type].append({
                "source_id": source_id,
                "target_id": target_id,
                **({} if edge_type == "SIMILAR_TO" else dict(attributes or {})),
            })
        for edge_type, batch in grouped.items():
            source_type, target_type = types[edge_type]
            try:
                self.source.call_tool("tigergraph__add_edges", {
                    "graph_name": self.graph_name,
                    "edge_type": edge_type,
                    "edges": [
                        {**item, "source_type": source_type, "target_type": target_type}
                        for item in batch
                    ],
                })
            except Exception:
                if not self._rest_fallback_enabled():
                    raise
                for item in batch:
                    self._rest().upsert_edge(
                        source_type, item["source_id"], edge_type, target_type,
                        item["target_id"], {key: value for key, value in item.items() if key not in {"source_id", "target_id", "source_type", "target_type"}},
                    )

    @staticmethod
    def _rest_fallback_enabled() -> bool:
        return os.getenv("TG_ENABLE_REST_FALLBACK", "false").strip().lower() in {"1", "true", "yes", "on"}

    def _mcp_vertex(self, vertex_type: str, vertex_id: str, attributes: Mapping[str, Any]) -> None:
        self.source.call_tool("tigergraph__add_node", {
            "graph_name": self.graph_name, "vertex_type": vertex_type,
            "vertex_id": vertex_id, "attributes": dict(attributes),
        })

    def _mcp_edge(self, source_vertex_type: str, source_vertex_id: str, edge_type: str, target_vertex_type: str, target_vertex_id: str, attributes: Mapping[str, Any] | None = None) -> None:
        self.source.call_tool("tigergraph__add_edge", {
            "graph_name": self.graph_name, "source_vertex_type": source_vertex_type,
            "source_vertex_id": source_vertex_id, "edge_type": edge_type,
            "target_vertex_type": target_vertex_type, "target_vertex_id": target_vertex_id,
            "attributes": dict(attributes or {}),
        })


def open_source(kind: str | None, *, transactions: str | None, identity: str | None, closed_cases: str | None) -> Any:
    """``tigergraph`` for the live graph, anything else for the CSV files."""
    if (kind or "").lower() in {"tigergraph", "tigergraph-mcp", "mcp"}:
        timeout_s = float(os.getenv("TG_MCP_TIMEOUT_S", "60"))
        return TigerGraphSource(timeout_s=timeout_s)
    from backend.sources.csv_source import CsvSource
    return CsvSource(transactions, identity, closed_cases)


__all__: Iterable[str] = ("MCPGraphWriter", "TigerGraphSource", "open_source")
