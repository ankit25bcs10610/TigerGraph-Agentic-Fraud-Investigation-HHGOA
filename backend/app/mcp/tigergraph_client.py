"""Credential-safe async client for TigerGraph's official MCP server.

The application deliberately communicates with TigerGraph only through the
official ``tigergraph-mcp`` stdio server.  This module owns the server process
and MCP session for the lifetime of one client context; application services do
not call TigerGraph REST endpoints directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client


class TigerGraphMCPError(RuntimeError):
    """Base exception for MCP integration failures."""


class TigerGraphMCPConfigurationError(TigerGraphMCPError):
    """Raised when the connection configuration is incomplete."""


class TigerGraphMCPServerUnavailableError(TigerGraphMCPError):
    """Raised when the local MCP command cannot be started or contacted."""


class TigerGraphMCPAuthenticationError(TigerGraphMCPError):
    """Raised when TigerGraph rejects the configured credentials."""


class TigerGraphMCPGraphNotFoundError(TigerGraphMCPError):
    """Raised when the configured graph is absent from the TigerGraph server."""


class TigerGraphMCPToolNotFoundError(TigerGraphMCPError):
    """Raised when a required MCP tool is not exposed by the server."""


class TigerGraphMCPVertexNotFoundError(TigerGraphMCPError):
    """Raised when an expected graph vertex is absent."""


class TigerGraphMCPMalformedResponseError(TigerGraphMCPError):
    """Raised when an MCP tool response cannot be interpreted safely."""


class TigerGraphMCPTimeoutError(TigerGraphMCPError):
    """Raised when an MCP startup or operation exceeds the configured timeout."""


_FENCED_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", flags=re.DOTALL)
_AUTH_ERROR_TERMS = (
    "auth",
    "credential",
    "token",
    "unauthorized",
    "forbidden",
    "permission denied",
    "authentication",
    "invalid password",
)
_GRAPH_ERROR_TERMS = ("graph not found", "graph does not exist", "unknown graph")


@dataclass(frozen=True)
class TigerGraphMCPConfig:
    """Validated runtime configuration supplied to the MCP child process."""

    host: str
    graph_name: str
    api_token: str | None
    username: str | None
    password: str | None
    secret: str | None
    tgcloud: str
    ssl_port: str
    timeout_s: float = 30.0
    _tg_values: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)

    @property
    def authentication_mode(self) -> str:
        """Return the effective credential strategy without exposing credentials."""
        return "api_token" if self.api_token else "username_password"

    @classmethod
    def from_environment(
        cls,
        *,
        dotenv_path: Path | str | None = None,
        environ: Mapping[str, str] | None = None,
        timeout_s: float = 30.0,
    ) -> "TigerGraphMCPConfig":
        """Read ``.env`` through python-dotenv and validate authentication.

        Real environment values override values in the dotenv file.  An API
        token has priority over username/password credentials, matching the
        official server's authentication behavior.
        """
        source_environment = dict(os.environ if environ is None else environ)
        env_file = Path(dotenv_path) if dotenv_path is not None else Path(".env")
        dotenv = dotenv_values(env_file) if env_file.is_file() else {}

        values = {
            key: str(value).strip()
            for key, value in dotenv.items()
            if key.startswith("TG_") and value is not None
        }
        values.update(
            {
                key: str(value).strip()
                for key, value in source_environment.items()
                if key.startswith("TG_") and value is not None
            }
        )

        def setting(name: str, default: str = "") -> str:
            return values.get(name, default).strip()

        host = setting("TG_HOST")
        graph_name = setting("TG_GRAPHNAME", "FraudInvestigation")
        api_token = setting("TG_API_TOKEN") or None
        username = setting("TG_USERNAME") or None
        password = setting("TG_PASSWORD") or None
        secret = setting("TG_SECRET") or None

        if not host:
            raise TigerGraphMCPConfigurationError(
                "TG_HOST is required. Configure it in .env or the environment."
            )
        if not graph_name:
            raise TigerGraphMCPConfigurationError("TG_GRAPHNAME must not be empty.")
        if not api_token and not (username and password):
            raise TigerGraphMCPConfigurationError(
                "Provide TG_API_TOKEN, or both TG_USERNAME and TG_PASSWORD."
            )
        if timeout_s <= 0:
            raise TigerGraphMCPConfigurationError("timeout_s must be greater than zero.")

        values["TG_HOST"] = host
        values["TG_GRAPHNAME"] = graph_name
        values["TG_TGCLOUD"] = setting("TG_TGCLOUD", "true")
        values["TG_SSL_PORT"] = setting("TG_SSL_PORT", "443")

        return cls(
            host=host,
            graph_name=graph_name,
            api_token=api_token,
            username=username,
            password=password,
            secret=secret,
            tgcloud=values["TG_TGCLOUD"],
            ssl_port=values["TG_SSL_PORT"],
            timeout_s=timeout_s,
            _tg_values=values,
        )

    def subprocess_environment(self) -> dict[str, str]:
        """Build the explicitly forwarded environment for the stdio server."""
        environment = {
            key: value
            for key, value in self._tg_values.items()
            if key.startswith("TG_") and value
        }
        environment.update(
            {
                "TG_HOST": self.host,
                "TG_GRAPHNAME": self.graph_name,
                "TG_TGCLOUD": self.tgcloud,
                "TG_SSL_PORT": self.ssl_port,
            }
        )

        # Keep the auth decision unambiguous inside the MCP child process.
        if self.api_token:
            environment["TG_API_TOKEN"] = self.api_token
            environment.pop("TG_USERNAME", None)
            environment.pop("TG_PASSWORD", None)
            environment.pop("TG_SECRET", None)
        else:
            environment.pop("TG_API_TOKEN", None)
            environment["TG_USERNAME"] = self.username or ""
            environment["TG_PASSWORD"] = self.password or ""
            if self.secret:
                environment["TG_SECRET"] = self.secret

        return {**get_default_environment(), **environment}

    def redact(self, message: str) -> str:
        """Remove configured credential values from diagnostics before logging."""
        redacted = str(message)
        for value in (self.api_token, self.username, self.password, self.secret):
            if value:
                redacted = redacted.replace(value, "[redacted]")
        return redacted


class TigerGraphMCPClient:
    """An async context manager for one official TigerGraph MCP session."""

    def __init__(
        self,
        config: TigerGraphMCPConfig | None = None,
        *,
        command: str = "tigergraph-mcp",
        command_args: tuple[str, ...] = (),
    ) -> None:
        self.config = config
        self.command = command
        self.command_args = command_args
        self._stdio_context: Any | None = None
        self._session_context: Any | None = None
        self._session: ClientSession | None = None
        self._tools: dict[str, dict[str, Any]] | None = None

    async def __aenter__(self) -> "TigerGraphMCPClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.close()

    @property
    def is_connected(self) -> bool:
        """Whether the MCP session has completed initialization."""
        return self._session is not None

    async def connect(self) -> None:
        """Start the stdio server once and initialize a reusable MCP session."""
        if self._session is not None:
            return

        if self.config is None:
            self.config = TigerGraphMCPConfig.from_environment()

        try:
            parameters = StdioServerParameters(
                command=self.command,
                args=list(self.command_args),
                env=self.config.subprocess_environment(),
            )
            self._stdio_context = stdio_client(parameters)
            read, write = await self._with_timeout(self._stdio_context.__aenter__())
            self._session_context = ClientSession(read, write)
            self._session = await self._with_timeout(self._session_context.__aenter__())
            await self._with_timeout(self._session.initialize())
        except FileNotFoundError as error:
            await self._close_contexts()
            raise TigerGraphMCPServerUnavailableError(
                "The 'tigergraph-mcp' command was not found. Install requirements.txt "
                "in the active Python environment."
            ) from error
        except asyncio.TimeoutError as error:
            await self._close_contexts()
            raise TigerGraphMCPTimeoutError(
                "Timed out while starting or initializing the TigerGraph MCP server."
            ) from error
        except Exception as error:
            await self._close_contexts()
            raise self._classified_error("Unable to initialize TigerGraph MCP", error) from error

    async def close(self) -> None:
        """Close the session and child process cleanly."""
        await self._close_contexts()

    async def list_tools(self) -> list[dict[str, Any]]:
        """List and cache the tools advertised by the running MCP server."""
        session = self._require_session()
        try:
            result = await self._with_timeout(session.list_tools())
        except asyncio.TimeoutError as error:
            raise TigerGraphMCPTimeoutError("Timed out while listing MCP tools.") from error
        except Exception as error:
            raise self._classified_error("Could not list TigerGraph MCP tools", error) from error

        raw_tools = getattr(result, "tools", None)
        if not isinstance(raw_tools, list):
            raise TigerGraphMCPMalformedResponseError(
                "The MCP server returned a tool list in an unexpected format."
            )

        tools = [self._model_to_dict(tool) for tool in raw_tools]
        if any(not isinstance(tool.get("name"), str) for tool in tools):
            raise TigerGraphMCPMalformedResponseError(
                "An MCP tool definition did not include a valid name."
            )
        self._tools = {tool["name"]: tool for tool in tools}
        return tools

    async def get_tool_schema(self, tool_name: str) -> dict[str, Any]:
        """Return an advertised input schema, failing clearly for missing tools."""
        if self._tools is None:
            await self.list_tools()
        assert self._tools is not None
        tool = self._tools.get(tool_name)
        if tool is None:
            raise TigerGraphMCPToolNotFoundError(
                f"Required TigerGraph MCP tool '{tool_name}' is not available."
            )
        schema = tool.get("inputSchema") or tool.get("input_schema")
        if not isinstance(schema, dict):
            raise TigerGraphMCPMalformedResponseError(
                f"MCP tool '{tool_name}' did not advertise an input schema."
            )
        return schema

    async def arguments_for(
        self, tool_name: str, candidate_values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Filter call arguments using the live MCP schema, not assumptions."""
        schema = await self.get_tool_schema(tool_name)
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise TigerGraphMCPMalformedResponseError(
                f"MCP tool '{tool_name}' has no usable input properties."
            )
        arguments = {
            key: value
            for key, value in candidate_values.items()
            if key in properties and value is not None
        }
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise TigerGraphMCPMalformedResponseError(
                f"MCP tool '{tool_name}' has an invalid required-field declaration."
            )
        missing = [field for field in required if field not in arguments]
        if missing:
            raise TigerGraphMCPMalformedResponseError(
                f"Cannot call MCP tool '{tool_name}': missing required fields {missing}."
            )
        return arguments

    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call one advertised tool and parse its structured TigerGraph response."""
        session = self._require_session()
        if self._tools is None:
            await self.list_tools()
        assert self._tools is not None
        if tool_name not in self._tools:
            raise TigerGraphMCPToolNotFoundError(
                f"Required TigerGraph MCP tool '{tool_name}' is not available."
            )

        try:
            result = await self._with_timeout(
                session.call_tool(tool_name, arguments=dict(arguments or {}))
            )
        except asyncio.TimeoutError as error:
            raise TigerGraphMCPTimeoutError(
                f"Timed out while calling TigerGraph MCP tool '{tool_name}'."
            ) from error
        except Exception as error:
            raise self._classified_error(
                f"TigerGraph MCP tool '{tool_name}' failed", error
            ) from error

        payload = self._parse_tool_result(result, tool_name)
        if payload.get("success") is False:
            message = str(payload.get("error") or payload.get("summary") or "Unknown error")
            raise self._classified_error(
                f"TigerGraph MCP tool '{tool_name}' reported an error", message
            )
        return payload

    async def health_check(self) -> dict[str, Any]:
        """Perform a lightweight list-graphs check against the configured graph."""
        arguments = await self.arguments_for("tigergraph__list_graphs", {})
        payload = await self.call_tool("tigergraph__list_graphs", arguments)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TigerGraphMCPMalformedResponseError(
                "list_graphs returned no structured graph data."
            )
        graphs = data.get("graphs")
        graph_names = {
            item if isinstance(item, str) else item.get("name")
            for item in graphs or []
            if isinstance(item, (str, dict))
        }
        if self.config is None or self.config.graph_name not in graph_names:
            graph_name = self.config.graph_name if self.config else "configured graph"
            raise TigerGraphMCPGraphNotFoundError(
                f"TigerGraph graph '{graph_name}' was not returned by list_graphs."
            )
        return {
            "status": "ok",
            "graph_name": self.config.graph_name,
            "tool_count": len(self._tools or {}),
        }

    async def _with_timeout(self, operation: Any) -> Any:
        assert self.config is not None
        return await asyncio.wait_for(operation, timeout=self.config.timeout_s)

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise TigerGraphMCPServerUnavailableError(
                "TigerGraph MCP is not connected. Use 'async with TigerGraphMCPClient()'."
            )
        return self._session

    async def _close_contexts(self) -> None:
        session_context, stdio_context = self._session_context, self._stdio_context
        self._session = None
        self._session_context = None
        self._stdio_context = None
        self._tools = None

        if session_context is not None:
            with suppress(Exception):
                await session_context.__aexit__(None, None, None)
        if stdio_context is not None:
            with suppress(Exception):
                await stdio_context.__aexit__(None, None, None)

    def _parse_tool_result(self, result: Any, tool_name: str) -> dict[str, Any]:
        structured_content = getattr(result, "structuredContent", None)
        if isinstance(structured_content, dict):
            return structured_content

        result_dict = self._model_to_dict(result)
        content = result_dict.get("content")
        if not isinstance(content, list):
            raise TigerGraphMCPMalformedResponseError(
                f"MCP tool '{tool_name}' returned no content list."
            )

        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            match = _FENCED_JSON.search(text)
            if not match:
                continue
            try:
                payload = json.loads(match.group(1))
            except json.JSONDecodeError as error:
                raise TigerGraphMCPMalformedResponseError(
                    f"MCP tool '{tool_name}' returned invalid JSON content."
                ) from error
            if isinstance(payload, dict):
                return payload

        if result_dict.get("isError") or result_dict.get("is_error"):
            error_text = " ".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
            raise self._classified_error(
                f"TigerGraph MCP tool '{tool_name}' returned an error", error_text
            )
        raise TigerGraphMCPMalformedResponseError(
            f"MCP tool '{tool_name}' did not return the documented structured JSON response."
        )

    @staticmethod
    def _model_to_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(mode="json")
            if isinstance(dumped, dict):
                return dumped
        raise TigerGraphMCPMalformedResponseError("MCP returned an unsupported model value.")

    def _classified_error(
        self, context: str, error: Exception | str
    ) -> TigerGraphMCPError:
        message = self.config.redact(str(error)) if self.config else str(error)
        lower_message = message.lower()
        if any(term in lower_message for term in _AUTH_ERROR_TERMS):
            return TigerGraphMCPAuthenticationError(f"{context}: authentication failed.")
        if any(term in lower_message for term in _GRAPH_ERROR_TERMS):
            return TigerGraphMCPGraphNotFoundError(f"{context}: configured graph was not found.")
        return TigerGraphMCPServerUnavailableError(f"{context}: {message}")
