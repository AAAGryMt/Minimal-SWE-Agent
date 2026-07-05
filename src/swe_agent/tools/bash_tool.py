"""Shell command execution tool."""

import asyncio
import platform
from typing import Any

from pydantic import Field, model_validator

from .base import Tool, ToolResult


class BashOutputResult(ToolResult):
    stdout: str = Field(description="The command's standard output")
    stderr: str = Field(description="The command's standard error output")
    exit_code: int = Field(description="The command's exit code")

    @model_validator(mode="after")
    def format_content(self) -> "BashOutputResult":
        output = ""
        if self.stdout:
            output += self.stdout
        if self.stderr:
            output += f"\n[stderr]:\n{self.stderr}"
        if self.exit_code != 0:
            output += f"\n[exit_code]:\n{self.exit_code}"
        if not output:
            output = "(no output)"
        self.content = output
        return self


class BashTool(Tool):
    def __init__(self, workspace_dir: str | None = None):
        self.is_windows = platform.system() == "Windows"
        self.shell_name = "PowerShell" if self.is_windows else "bash"
        self.workspace_dir = workspace_dir

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return """Execute bash commands.

For terminal operations like git, npm, docker, etc. DO NOT use for file operations - use specialized tools.

Parameters:
  - command (required): Bash command to execute
  - timeout (optional): Timeout in seconds (default: 120, max: 600)

Tips:
  - Quote file paths with spaces: cd "My Documents"
  - Chain dependent commands with &&: git add . && git commit -m "msg"
  - Use absolute paths instead of cd when possible"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": f"The {self.shell_name} command to execute. Quote file paths with spaces using double quotes.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Optional: Timeout in seconds (default: 120, max: 600).",
                    "default": 120,
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, timeout: int = 120) -> ToolResult:
        try:
            if timeout > 600:
                timeout = 600
            elif timeout < 1:
                timeout = 120

            if self.is_windows:
                process = await asyncio.create_subprocess_exec(
                    "powershell.exe", "-NoProfile", "-Command", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.workspace_dir,
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.workspace_dir,
                )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                return BashOutputResult(
                    success=False,
                    error=f"Command timed out after {timeout} seconds",
                    stdout="",
                    stderr="",
                    exit_code=-1,
                )
            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            is_success = process.returncode == 0
            error_msg = None
            if not is_success:
                error_msg = f"Command failed with exit code {process.returncode}"
                if stderr_text:
                    error_msg += f"\n{stderr_text.strip()}"
            return BashOutputResult(
                success=is_success,
                error=error_msg,
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=process.returncode or 0,
            )
        except Exception as e:
            return BashOutputResult(success=False, error=str(e), stdout="", stderr=str(e), exit_code=-1)
