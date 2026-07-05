import asyncio
from typing import Any

from swe_agent.core.tool import BaseTool, ToolResult


class GrepTool(BaseTool):
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search file contents using regex"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for",
                },
                "include": {
                    "type": "string",
                    "description": "File glob pattern to filter (e.g. *.py)",
                    "default": "",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, include: str = "") -> ToolResult:
        try:
            if ".." in include:
                return ToolResult(success=False, error="Path traversal detected in include pattern")
            cmd = ["rg", "-n", pattern]
            if include:
                cmd.extend(["-g", include])
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace_dir,
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode(errors="replace")
            if not output.strip():
                return ToolResult(success=True, content="No matches found")
            return ToolResult(success=True, content=output.strip())
        except FileNotFoundError:
            return ToolResult(
                success=False,
                error="'rg' (ripgrep) not found. Install with: brew install ripgrep",
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
