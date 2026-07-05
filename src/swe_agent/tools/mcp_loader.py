from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from swe_agent.core.tool import BaseTool, ToolResult

ConnectionType = Literal["stdio", "sse", "http", "streamable_http"]

_mcp_connections: list[MCPServerConnection] = []


class MCPTool(BaseTool):
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        session: ClientSession,
        execute_timeout: float = 60.0,
    ):
        self._name = name
        self._description = description
        self._parameters = parameters
        self._session = session
        self._execute_timeout = execute_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs) -> ToolResult:
        try:
            async with asyncio.timeout(self._execute_timeout):
                result = await self._session.call_tool(self._name, arguments=kwargs)

            content_parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    content_parts.append(item.text)
                else:
                    content_parts.append(str(item))

            content_str = "\n".join(content_parts)
            is_error = result.isError if hasattr(result, "isError") else False

            return ToolResult(success=not is_error, content=content_str, error=None if not is_error else "Tool returned error")

        except TimeoutError:
            return ToolResult(success=False, content="", error=f"MCP tool execution timed out after {self._execute_timeout}s")
        except Exception as e:
            return ToolResult(success=False, content="", error=f"MCP tool execution failed: {str(e)}")


class MCPServerConnection:
    def __init__(
        self,
        name: str,
        connection_type: ConnectionType = "stdio",
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        connect_timeout: float = 10.0,
        execute_timeout: float = 60.0,
        sse_read_timeout: float = 120.0,
    ):
        self.name = name
        self.connection_type = connection_type
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.url = url
        self.headers = headers or {}
        self.connect_timeout = connect_timeout
        self.execute_timeout = execute_timeout
        self.sse_read_timeout = sse_read_timeout
        self.session: ClientSession | None = None
        self.exit_stack: AsyncExitStack | None = None
        self.tools: list[MCPTool] = []

    async def connect(self) -> bool:
        self.exit_stack = AsyncExitStack()
        try:
            async with asyncio.timeout(self.connect_timeout):
                if self.connection_type == "stdio":
                    read_stream, write_stream = await self.exit_stack.enter_async_context(
                        stdio_client(StdioServerParameters(command=self.command, args=self.args, env=self.env if self.env else None))
                    )
                elif self.connection_type == "sse":
                    read_stream, write_stream = await self.exit_stack.enter_async_context(
                        sse_client(url=self.url, headers=self.headers if self.headers else None, timeout=self.connect_timeout, sse_read_timeout=self.sse_read_timeout)
                    )
                else:
                    read_stream, write_stream, _ = await self.exit_stack.enter_async_context(
                        streamablehttp_client(url=self.url, headers=self.headers if self.headers else None, timeout=self.connect_timeout, sse_read_timeout=self.sse_read_timeout)
                    )

                session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
                self.session = session
                await session.initialize()

                tools_list = await session.list_tools()

            for tool in tools_list.tools:
                params = tool.inputSchema if hasattr(tool, "inputSchema") else {}
                self.tools.append(MCPTool(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=params,
                    session=session,
                    execute_timeout=self.execute_timeout,
                ))

            print(f"  {chr(10003)} MCP server '{self.name}' connected ({len(self.tools)} tools)")
            return True

        except TimeoutError:
            print(f"  {chr(10007)} MCP server '{self.name}' connection timed out")
            await self.disconnect()
            return False
        except Exception as e:
            print(f"  {chr(10007)} MCP server '{self.name}' failed: {e}")
            await self.disconnect()
            return False

    async def disconnect(self):
        if self.exit_stack:
            try:
                await self.exit_stack.aclose()
            except Exception:
                pass
            finally:
                self.exit_stack = None
                self.session = None


async def load_mcp_tools_async(config_path: str) -> list[BaseTool]:
    global _mcp_connections

    config_file = Path(config_path)
    if not config_file.exists():
        print(f"  MCP config not found: {config_path}")
        return []

    with open(config_file, encoding="utf-8") as f:
        config = json.load(f)

    mcp_servers = config.get("mcpServers", {})
    if not mcp_servers:
        return []

    all_tools: list[BaseTool] = []

    for server_name, server_config in mcp_servers.items():
        if server_config.get("disabled", False):
            continue

        url = server_config.get("url")
        command = server_config.get("command")
        conn_type = server_config.get("type", "streamable_http" if url else "stdio")

        if conn_type == "stdio" and not command:
            print(f"  Skipping MCP server '{server_name}': no command")
            continue
        if conn_type in ("sse", "http", "streamable_http") and not url:
            print(f"  Skipping MCP server '{server_name}': no url")
            continue

        connection = MCPServerConnection(
            name=server_name,
            connection_type=conn_type,
            command=command,
            args=server_config.get("args", []),
            env=server_config.get("env", {}),
            url=url,
            headers=server_config.get("headers", {}),
            connect_timeout=server_config.get("connect_timeout", 10.0),
            execute_timeout=server_config.get("execute_timeout", 60.0),
            sse_read_timeout=server_config.get("sse_read_timeout", 120.0),
        )

        if await connection.connect():
            _mcp_connections.append(connection)
            all_tools.extend(connection.tools)

    return all_tools


async def cleanup_mcp_connections():
    global _mcp_connections
    for conn in _mcp_connections:
        await conn.disconnect()
    _mcp_connections.clear()
