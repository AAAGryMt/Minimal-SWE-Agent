"""工具抽象层 —— 定义所有工具的统一接口和数据模型。"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    """工具执行结果 —— 成功返回 content，失败返回 error。"""
    success: bool
    content: str = ""
    error: str | None = None


class BaseTool(ABC):
    """所有工具的抽象基类。

    子类必须实现 name / description / parameters（属性）和 execute（异步方法）。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一标识，如 "bash"、"read"、"grep" 。"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具用途说明，注入 LLM 的 system prompt。"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """工具参数 JSON Schema，描述每个参数的类型和含义。"""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具逻辑，传入具名参数，返回 ToolResult。"""
        ...
