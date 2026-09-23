"""Read-only health and schema checks for the known fraud graph."""

from __future__ import annotations

from typing import Any, Iterable

from .tigergraph_client import TigerGraphMCPMalformedResponseError


EXPECTED_GRAPH_NAME = "FraudInvestigationGraph"
EXPECTED_VERTEX_TYPES = frozenset(
    {
        "Customer",
        "Card",
        "Transaction",
        "DeviceProfile",
        "EmailDomain",
        "BillingRegion",
        "ClosedCase",
        "InvestigationCase",
    }
)
EXPECTED_EDGE_TYPES = frozenset(
    {
        "OWNS",
        "made",
        "FROM_DEVICE",
        "PURCHASER_EMAIL",
        "BILLED_IN",
        "NEXT",
        "INVOLVES",
        "ON_CARD",
        "CONNECTED_TO",
    }
)


class TigerGraphMCPSchemaError(TigerGraphMCPMalformedResponseError):
    """Raised when the connected graph does not match the required schema."""


def _names(entries: Any) -> set[str]:
    if not isinstance(entries, Iterable) or isinstance(entries, (str, bytes, dict)):
        return set()
    names: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            names.add(entry)
            continue
        if not isinstance(entry, dict):
            continue
        for key in ("Name", "name", "VertexTypeName", "EdgeTypeName"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                names.add(value)
                break
    return names


def verify_fraud_graph_schema(schema_data: dict[str, Any]) -> dict[str, list[str]]:
    """Validate only the vertex and edge names used by this project.

    The result contains discovered names for safe diagnostics; it deliberately
    does not modify the target graph or infer undocumented properties.
    """
    schema = schema_data.get("schema")
    if not isinstance(schema, dict):
        raise TigerGraphMCPSchemaError("get_graph_schema returned no schema object.")

    vertex_types = _names(schema.get("VertexTypes"))
    edge_types = _names(schema.get("EdgeTypes"))
    missing_vertices = sorted(EXPECTED_VERTEX_TYPES - vertex_types)
    missing_edges = sorted(EXPECTED_EDGE_TYPES - edge_types)
    if missing_vertices or missing_edges:
        details: list[str] = []
        if missing_vertices:
            details.append(f"missing vertex types: {', '.join(missing_vertices)}")
        if missing_edges:
            details.append(f"missing edge types: {', '.join(missing_edges)}")
        raise TigerGraphMCPSchemaError("Graph schema mismatch: " + "; ".join(details))

    return {
        "vertex_types": sorted(vertex_types),
        "edge_types": sorted(edge_types),
    }
