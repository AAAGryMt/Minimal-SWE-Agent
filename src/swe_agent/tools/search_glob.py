from pathlib import Path
from typing import Any

from swe_agent.core.tool import BaseTool, ToolResult


class GlobTool(BaseTool):
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "Find files matching a glob pattern"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The glob pattern to match (e.g. **/*.py)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str) -> ToolResult:
        try:
            root = Path(self.workspace_dir).resolve()
            files = []
            for f in root.rglob(pattern):
                if not f.is_file():
                    continue
                resolved = f.resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    continue
                files.append(str(resolved.relative_to(root)))
            files.sort()
            if not files:
                return ToolResult(success=True, content="No files matched")
            output = "\n".join(files)
            return ToolResult(success=True, content=f"Found {len(files)} files:\n{output}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
