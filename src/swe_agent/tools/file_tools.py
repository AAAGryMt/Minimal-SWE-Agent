"""File operation tools."""

from pathlib import Path
from typing import Any

import tiktoken

from .base import Tool, ToolResult
from .security import resolve_safe_path


def truncate_text_by_tokens(text: str, max_tokens: int) -> str:
    encoding = tiktoken.get_encoding("cl100k_base")
    token_count = len(encoding.encode(text))
    if token_count <= max_tokens:
        return text
    char_count = len(text)
    ratio = token_count / char_count
    chars_per_half = int((max_tokens / 2) / ratio * 0.95)
    head_part = text[:chars_per_half]
    last_newline_head = head_part.rfind("\n")
    if last_newline_head > 0:
        head_part = head_part[:last_newline_head]
    tail_part = text[-chars_per_half:]
    first_newline_tail = tail_part.find("\n")
    if first_newline_tail > 0:
        tail_part = tail_part[first_newline_tail + 1:]
    truncation_note = f"\n\n... [Content truncated: {token_count} tokens -> ~{max_tokens} tokens limit] ...\n\n"
    return head_part + truncation_note + tail_part


class ReadTool(Tool):
    def __init__(self, workspace_dir: str = "."):
        self.workspace_dir = Path(workspace_dir).absolute()

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read file contents from the filesystem. Output always includes line numbers "
            "in format 'LINE_NUMBER|LINE_CONTENT' (1-indexed). Supports reading partial content "
            "by specifying line offset and limit for large files."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting line number (1-indexed). Use for large files to read from specific line",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of lines to read. Use with offset for large files to read in chunks",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, offset: int | None = None, limit: int | None = None) -> ToolResult:
        try:
            file_path = resolve_safe_path(str(self.workspace_dir), path)
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()
            start = (offset - 1) if offset else 0
            end = (start + limit) if limit else len(lines)
            if start < 0:
                start = 0
            if end > len(lines):
                end = len(lines)
            selected_lines = lines[start:end]
            numbered_lines = []
            for i, line in enumerate(selected_lines, start=start + 1):
                line_content = line.rstrip("\n")
                numbered_lines.append(f"{i:6d}|{line_content}")
            content = "\n".join(numbered_lines)
            content = truncate_text_by_tokens(content, 32000)
            return ToolResult(success=True, content=content)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class WriteTool(Tool):
    def __init__(self, workspace_dir: str = "."):
        self.workspace_dir = Path(workspace_dir).absolute()

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. Will overwrite existing files completely. "
            "For existing files, you should read the file first using read_file. "
            "Prefer editing existing files over creating new ones unless explicitly needed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "Complete content to write (will replace existing content)",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str) -> ToolResult:
        try:
            file_path = resolve_safe_path(str(self.workspace_dir), path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, content=f"Successfully wrote to {file_path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class EditTool(Tool):
    def __init__(self, workspace_dir: str = "."):
        self.workspace_dir = Path(workspace_dir).absolute()

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Perform exact string replacement in a file. The old_str must match exactly "
            "and appear uniquely in the file, otherwise the operation will fail. "
            "You must read the file first before editing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                },
                "old_str": {
                    "type": "string",
                    "description": "Exact string to find and replace (must be unique in file)",
                },
                "new_str": {
                    "type": "string",
                    "description": "Replacement string",
                },
            },
            "required": ["path", "old_str", "new_str"],
        }

    async def execute(self, path: str, old_str: str, new_str: str) -> ToolResult:
        try:
            file_path = resolve_safe_path(str(self.workspace_dir), path)
            if not file_path.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            content = file_path.read_text(encoding="utf-8")
            if old_str not in content:
                return ToolResult(success=False, error=f"Text not found in file: {old_str}")
            new_content = content.replace(old_str, new_str)
            file_path.write_text(new_content, encoding="utf-8")
            return ToolResult(success=True, content=f"Successfully edited {file_path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
