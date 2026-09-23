"""Credential-gated real integration coverage for the official MCP server."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.app.mcp.tigergraph_client import (
    TigerGraphMCPConfig,
    TigerGraphMCPConfigurationError,
)
from scripts.test_tigergraph_mcp import run_smoke_test


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _configured_connection() -> TigerGraphMCPConfig | None:
    try:
        return TigerGraphMCPConfig.from_environment(dotenv_path=PROJECT_ROOT / ".env")
    except TigerGraphMCPConfigurationError:
        return None


CONFIG = _configured_connection()


@pytest.mark.integration
@pytest.mark.skipif(CONFIG is None, reason="TigerGraph MCP credentials are not configured")
def test_official_mcp_server_against_loaded_fraud_graph() -> None:
    """Run the same non-mutating checks exposed by the operator smoke command."""
    assert CONFIG is not None
    result = asyncio.run(run_smoke_test(CONFIG))

    assert result["graphs"] == ["FraudInvestigation"] or "FraudInvestigation" in result[
        "graphs"
    ]
    assert result["tool_count"] > 0
    assert result["owns"]["count"] > 0
    assert result["made"]["count"] > 0
