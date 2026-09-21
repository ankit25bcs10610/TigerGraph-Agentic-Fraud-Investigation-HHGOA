#!/usr/bin/env python3
"""Run a real, read-only smoke test through the official TigerGraph MCP server.

This script makes no schema, data, or policy changes.  It requires valid local
credentials in ``.env`` or the environment and exits non-zero on any mismatch.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.mcp.health import (  # noqa: E402
    EXPECTED_EDGE_TYPES,
    EXPECTED_GRAPH_NAME,
    EXPECTED_VERTEX_TYPES,
    verify_fraud_graph_schema,
)
from backend.app.mcp.tigergraph_client import (  # noqa: E402
    TigerGraphMCPClient,
    TigerGraphMCPConfig,
    TigerGraphMCPError,
)
from backend.app.services.tigergraph_service import TigerGraphService  # noqa: E402


EXPECTED_VERTEX_COUNTS = {
    "Customer": 13_553,
    "Card": 14_318,
    "Transaction": 590_742,
    "DeviceProfile": 9_776,
    "EmailDomain": 59,
    "BillingRegion": 332,
    "ClosedCase": 5_565,
    "InvestigationCase": 0,
}
EXPECTED_EDGE_COUNTS = {
    "OWNS": 14_318,
    "made": 590_742,
    "FROM_DEVICE": 141_055,
    "PURCHASER_EMAIL": 496_262,
    "BILLED_IN": 525_003,
    "NEXT": 576_424,
    "INVOLVES": 14_955,
    "ON_CARD": 5_565,
    "CONNECTED_TO": 92,
}


def _print_result(label: str, value: Any) -> None:
    print(f"\n{label}:")
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _identifiers(value: Any) -> set[str]:
    """Collect server-returned vertex identifiers without assuming response nesting."""
    identifiers: set[str] = set()
    if isinstance(value, dict):
        for key in ("v_id", "vertex_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, (str, int)):
                identifiers.add(str(candidate))
        for nested in value.values():
            identifiers.update(_identifiers(nested))
    elif isinstance(value, list):
        for nested in value:
            identifiers.update(_identifiers(nested))
    return identifiers


async def run_smoke_test(config: TigerGraphMCPConfig) -> dict[str, Any]:
    """Verify the configured graph and representative known records via MCP."""
    if config.graph_name != EXPECTED_GRAPH_NAME:
        raise TigerGraphMCPError(
            f"Smoke test expects graph '{EXPECTED_GRAPH_NAME}', got a different TG_GRAPHNAME."
        )

    async with TigerGraphMCPClient(config) as client:
        # First discover tool names and schemas. Every service call below filters
        # its arguments through these advertised schemas before execution.
        tools = await client.list_tools()
        tool_names = sorted(tool["name"] for tool in tools)
        print(f"MCP tools discovered ({len(tool_names)}):")
        for tool_name in tool_names:
            print(f"- {tool_name}")

        service = TigerGraphService(client)
        graphs = await service.list_graphs()
        _print_result("list_graphs result", graphs)
        await service.ensure_graph_exists()

        schema = await service.get_schema()
        schema_summary = verify_fraud_graph_schema(schema)
        _print_result("get_graph_schema result", schema)
        _print_result("validated schema type names", schema_summary)

        vertex_counts = {
            vertex_type: await service.get_vertex_count(vertex_type)
            for vertex_type in sorted(EXPECTED_VERTEX_TYPES)
        }
        edge_counts = {
            edge_type: await service.get_edge_count(edge_type)
            for edge_type in sorted(EXPECTED_EDGE_TYPES)
        }
        _print_result("vertex counts", vertex_counts)
        _print_result("edge counts", edge_counts)
        if vertex_counts != EXPECTED_VERTEX_COUNTS:
            raise TigerGraphMCPError(
                "Vertex counts do not match the validated expected graph state."
            )
        if edge_counts != EXPECTED_EDGE_COUNTS:
            raise TigerGraphMCPError(
                "Edge counts do not match the validated expected graph state."
            )

        customer = await service.get_customer("C12382")
        _print_result("Customer C12382", customer)
        owns = await service.get_neighbors(
            "Customer",
            "C12382",
            edge_type="OWNS",
            target_vertex_type="Card",
            limit=25,
        )
        _print_result("Customer C12382 OWNS Card neighbors", owns)
        if "C12382-K1" not in _identifiers(owns):
            raise TigerGraphMCPError(
                "Expected Card C12382-K1 was not returned from Customer C12382 via OWNS."
            )

        made = await service.get_neighbors(
            "Card",
            "C12382-K1",
            edge_type="made",
            target_vertex_type="Transaction",
            limit=25,
        )
        _print_result("Card C12382-K1 made Transaction neighbors", made)
        if made["count"] <= 0:
            raise TigerGraphMCPError(
                "Card C12382-K1 returned no transactions through the 'made' edge."
            )

        transaction = await service.get_transaction("3514030")
        _print_result("Transaction 3514030", transaction)
        transaction_neighbors: dict[str, dict[str, Any]] = {}
        for edge_type, target_vertex_type in (
            ("FROM_DEVICE", "DeviceProfile"),
            ("PURCHASER_EMAIL", "EmailDomain"),
            ("BILLED_IN", "BillingRegion"),
        ):
            transaction_neighbors[edge_type] = await service.get_neighbors(
                "Transaction",
                "3514030",
                edge_type=edge_type,
                target_vertex_type=target_vertex_type,
                limit=25,
            )
            _print_result(
                f"Transaction 3514030 {edge_type} {target_vertex_type} neighbors",
                transaction_neighbors[edge_type],
            )

        return {
            "tool_count": len(tool_names),
            "graphs": graphs,
            "schema": schema_summary,
            "vertex_counts": vertex_counts,
            "edge_counts": edge_counts,
            "customer": customer,
            "owns": owns,
            "made": made,
            "transaction": transaction,
            "transaction_neighbors": transaction_neighbors,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="dotenv file to read (default: project .env)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="timeout for each MCP startup or call (default: 30)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = TigerGraphMCPConfig.from_environment(
            dotenv_path=args.env_file,
            timeout_s=args.timeout_seconds,
        )
        asyncio.run(run_smoke_test(config))
    except TigerGraphMCPError as error:
        print(f"TigerGraph MCP smoke test failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("TigerGraph MCP smoke test interrupted.", file=sys.stderr)
        return 130

    print("\nTigerGraph MCP smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
