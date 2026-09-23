"""Unit tests for the credential-safe TigerGraph MCP boundary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.mcp import tigergraph_client as client_module
from backend.app.mcp.health import (
    EXPECTED_EDGE_TYPES,
    EXPECTED_VERTEX_TYPES,
    TigerGraphMCPSchemaError,
    verify_fraud_graph_schema,
)
from backend.app.mcp.tigergraph_client import (
    TigerGraphMCPClient,
    TigerGraphMCPConfig,
    TigerGraphMCPConfigurationError,
    TigerGraphMCPVertexNotFoundError,
)
from backend.app.services.tigergraph_service import TigerGraphService


def configured_environment(**overrides: str) -> dict[str, str]:
    values = {
        "TG_HOST": "https://example.tigergraph.cloud",
        "TG_GRAPHNAME": "FraudInvestigation",
        "TG_API_TOKEN": "token-value",
        "TG_SECRET": "",
        "TG_TGCLOUD": "true",
        "TG_SSL_PORT": "443",
    }
    values.update(overrides)
    return values


def test_config_prefers_api_token_without_exposing_alternative_credentials() -> None:
    config = TigerGraphMCPConfig.from_environment(
        environ=configured_environment(TG_USERNAME="analyst", TG_PASSWORD="password")
    )

    assert config.authentication_mode == "api_token"
    child_environment = config.subprocess_environment()
    assert child_environment["TG_API_TOKEN"] == "token-value"
    assert "TG_USERNAME" not in child_environment
    assert "TG_PASSWORD" not in child_environment
    assert "token-value" not in config.redact("failed token-value authentication")


def test_config_accepts_username_password_when_no_token_exists() -> None:
    config = TigerGraphMCPConfig.from_environment(
        environ=configured_environment(
            TG_API_TOKEN="", TG_USERNAME="analyst", TG_PASSWORD="password", TG_SECRET="secret"
        )
    )

    assert config.authentication_mode == "username_password"
    child_environment = config.subprocess_environment()
    assert child_environment["TG_USERNAME"] == "analyst"
    assert child_environment["TG_PASSWORD"] == "password"
    assert child_environment["TG_SECRET"] == "secret"
    assert "TG_API_TOKEN" not in child_environment


def test_config_accepts_database_secret_without_token_or_password() -> None:
    config = TigerGraphMCPConfig.from_environment(
        environ=configured_environment(TG_API_TOKEN="", TG_SECRET="database-secret")
    )

    assert config.authentication_mode == "secret"
    child_environment = config.subprocess_environment()
    assert child_environment["TG_SECRET"] == "database-secret"
    assert "TG_API_TOKEN" not in child_environment
    assert child_environment["TG_USERNAME"] == ""
    assert child_environment["TG_PASSWORD"] == ""


def test_config_rejects_missing_authentication() -> None:
    with pytest.raises(TigerGraphMCPConfigurationError, match="TG_API_TOKEN"):
        TigerGraphMCPConfig.from_environment(
            environ=configured_environment(TG_API_TOKEN="", TG_USERNAME="", TG_PASSWORD="")
        )


class _FakeStdioContext:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> tuple[str, str]:
        self.entered = True
        return "reader", "writer"

    async def __aexit__(self, *_: Any) -> None:
        self.exited = True


class _FakeSessionContext:
    def __init__(self) -> None:
        self.initialized = False
        self.exited = False

    async def __aenter__(self) -> "_FakeSessionContext":
        return self

    async def __aexit__(self, *_: Any) -> None:
        self.exited = True

    async def initialize(self) -> None:
        self.initialized = True

    async def list_tools(self) -> Any:
        return SimpleNamespace(
            tools=[
                {
                    "name": "tigergraph__list_graphs",
                    "inputSchema": {"type": "object", "properties": {}, "required": []},
                }
            ]
        )


def test_client_starts_one_stdio_session_and_lists_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    stdio_context = _FakeStdioContext()
    session_context = _FakeSessionContext()
    captured: dict[str, Any] = {}

    def fake_stdio(parameters: Any) -> _FakeStdioContext:
        captured["parameters"] = parameters
        return stdio_context

    monkeypatch.setattr(client_module, "stdio_client", fake_stdio)
    monkeypatch.setattr(client_module, "ClientSession", lambda *_: session_context)
    client = TigerGraphMCPClient(
        TigerGraphMCPConfig.from_environment(environ=configured_environment())
    )

    async def exercise() -> None:
        await client.connect()
        assert client.is_connected
        tools = await client.list_tools()
        assert [tool["name"] for tool in tools] == ["tigergraph__list_graphs"]
        await client.close()

    asyncio.run(exercise())

    assert stdio_context.entered and stdio_context.exited
    assert session_context.initialized and session_context.exited
    assert captured["parameters"].command == "tigergraph-mcp"
    assert captured["parameters"].env["TG_GRAPHNAME"] == "FraudInvestigation"


def test_client_parses_documented_fenced_json_response() -> None:
    client = TigerGraphMCPClient(
        TigerGraphMCPConfig.from_environment(environ=configured_environment())
    )
    result = {
        "content": [
            {
                "type": "text",
                "text": "```json\n{\"success\": true, \"data\": {\"count\": 3}}\n```\n",
            }
        ]
    }

    assert client._parse_tool_result(result, "tigergraph__get_vertex_count") == {
        "success": True,
        "data": {"count": 3},
    }


class _FakeMCPClient:
    def __init__(self, response_data: dict[str, Any]) -> None:
        self.config = SimpleNamespace(graph_name="FraudInvestigation")
        self.response_data = response_data
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def arguments_for(
        self, tool_name: str, candidate_values: dict[str, Any]
    ) -> dict[str, Any]:
        return {key: value for key, value in candidate_values.items() if value is not None}

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, arguments))
        return {"success": True, "data": self.response_data}


def test_service_uses_only_mcp_tool_calls_for_customer_retrieval() -> None:
    fake_client = _FakeMCPClient({"v_id": "C12382", "v_type": "Customer"})
    service = TigerGraphService(fake_client)  # type: ignore[arg-type]

    customer = asyncio.run(service.get_customer("C12382"))

    assert customer["v_id"] == "C12382"
    assert fake_client.calls == [
        (
            "tigergraph__get_node",
            {
                "graph_name": "FraudInvestigation",
                "vertex_type": "Customer",
                "vertex_id": "C12382",
            },
        )
    ]


def test_service_rejects_missing_vertex_instead_of_returning_empty_data() -> None:
    service = TigerGraphService(_FakeMCPClient({}))  # type: ignore[arg-type]

    with pytest.raises(TigerGraphMCPVertexNotFoundError, match="was not found"):
        asyncio.run(service.get_transaction("missing"))


def test_schema_validation_accepts_expected_schema_names() -> None:
    schema = {
        "schema": {
            "VertexTypes": [{"Name": name} for name in EXPECTED_VERTEX_TYPES],
            "EdgeTypes": [{"Name": name} for name in EXPECTED_EDGE_TYPES],
        }
    }

    verified = verify_fraud_graph_schema(schema)

    assert set(verified["vertex_types"]) == EXPECTED_VERTEX_TYPES
    assert set(verified["edge_types"]) == EXPECTED_EDGE_TYPES


def test_schema_validation_reports_missing_types() -> None:
    with pytest.raises(TigerGraphMCPSchemaError, match="missing vertex types"):
        verify_fraud_graph_schema({"schema": {"VertexTypes": [], "EdgeTypes": []}})
