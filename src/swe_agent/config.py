"""配置模型与加载逻辑 —— Pydantic 模型定义 + 多级配置文件查找。

优先级（从低到高）：
    Pydantic 默认值 → config.yaml → 环境变量（.env）→ CLI 参数 → REPL /config 命令
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class LLMConfig(BaseModel):
    """LLM 连接配置 —— 支持任意 LiteLLM 兼容的 provider。"""
    model: str = "gpt-4o"
    api_key: str | None = None
    api_base: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _empty_str_to_none(cls, data):
        """将 YAML 中空字符串的 api_key/api_base 转为 None，避免传空值给 litellm。"""
        if isinstance(data, dict):
            for k in ("api_key", "api_base"):
                if k in data and isinstance(data[k], str) and data[k] == "":
                    data[k] = None
        return data


class AgentConfig(BaseModel):
    """Agent 行为配置 —— 迭代上限、工作目录、系统提示词路径。"""
    max_iterations: int = 10
    workspace_dir: str = "."
    system_prompt_path: str = "configs/SYSTEM_PROMPT.md"


class MemoryConfig(BaseModel):
    """mem0 记忆配置 —— 本地向量数据库路径、开关、压缩 LLM 凭证。"""
    directory: str = "~/.minimal-swe-agent/memories"
    enabled: bool = True
    llm_model: str | None = None        # 压缩内存时用的 LLM，不填则复用主 LLM
    api_key: str | None = None
    api_base: str | None = None
    compact_max_tokens: int = 2000       # 压缩摘要的 token 上限
    system_prompt: str | None = None     # 运行时自定义系统提示词

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        """YAML 预处理：空字符串 → None，字符串 "true"/"false" → bool。"""
        if isinstance(data, dict):
            for k in ("llm_model", "api_key", "api_base", "system_prompt"):
                if k in data and isinstance(data[k], str) and data[k] == "":
                    data[k] = None
            if "enabled" in data and isinstance(data["enabled"], str):
                data["enabled"] = data["enabled"].lower() == "true"
        return data


class ToolsConfig(BaseModel):
    """工具开关 —— 控制 MCP 和 Skills 的启用及配置文件路径。"""
    enable_mcp: bool = False             # 默认关闭，需显式开启
    mcp_config_path: str = "mcp.json"    # MCP 服务器配置文件路径
    enable_skills: bool = False          # 默认关闭
    skills_dir: str = "skills"           # Skills 定义文件的搜索目录


class Config(BaseModel):
    """顶层配置聚合 —— 包含 LLM、Agent、Memory、Tools 四个子模块。

    通过 Config.load() 从 YAML 文件加载，查找优先级：
        1) ./config.yaml（当前目录）
        2) ~/.minimal-swe-agent/config.yaml（用户目录）
        3) <package>/config.yaml（包根目录）
        4) <package>/configs/config.yaml（包内 configs 子目录）
    """
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @classmethod
    def _get_package_dir(cls) -> Path:
        """返回 swe_agent 包目录（本文件所在目录）。"""
        return Path(__file__).resolve().parent

    @classmethod
    def find_config_file(cls, filename: str = "config.yaml") -> Path | None:
        """按优先级查找配置文件，返回第一个存在的文件路径。

        可传不同文件名用于查找 mcp.json、SYSTEM_PROMPT.md 等。
        """
        # 1) 当前工作目录
        cwd_config = Path.cwd() / filename
        if cwd_config.exists():
            return cwd_config

        # 2) 用户主目录
        home_config = Path.home() / ".minimal-swe-agent" / filename
        if home_config.exists():
            return home_config

        # 3) 包根目录
        pkg_config = cls._get_package_dir() / filename
        if pkg_config.exists():
            return pkg_config

        # 4) 包内 configs 子目录
        pkg_config_sub = cls._get_package_dir() / "configs" / filename
        if pkg_config_sub.exists():
            return pkg_config_sub

        return None

    @classmethod
    def load(cls) -> Config:
        """加载配置：.env → YAML → 环境变量覆盖。"""
        _load_dotenv()

        config_path = cls.find_config_file()
        if config_path:
            import yaml
            with open(config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}

        config = cls.model_validate(raw)
        config._merge_env()
        return config

    def _merge_env(self):
        """用环境变量覆盖 LLM 配置字段。

        环境变量映射（字母全大写）：
            LLM_MODEL, LLM_API_KEY, LLM_API_BASE, LLM_MAX_TOKENS, LLM_TEMPERATURE
        """
        env_map = {
            "model": os.getenv("LLM_MODEL"),
            "api_key": os.getenv("LLM_API_KEY"),
            "api_base": os.getenv("LLM_API_BASE"),
            "max_tokens": os.getenv("LLM_MAX_TOKENS"),
            "temperature": os.getenv("LLM_TEMPERATURE"),
        }
        for field, value in env_map.items():
            if value:
                if field == "max_tokens":
                    setattr(self.llm, field, int(value))
                elif field == "temperature":
                    setattr(self.llm, field, float(value))
                else:
                    setattr(self.llm, field, value)

    def apply_cli_overrides(
        self,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
    ):
        """用 CLI 参数覆盖 LLM 配置（优先级高于 env 和 yaml）。"""
        if model:
            self.llm.model = model
        if api_key:
            self.llm.api_key = api_key
        if api_base:
            self.llm.api_base = api_base

    def save(self, path: Path | None = None) -> Path:
        """将当前完整配置序列化写入 YAML 文件，默认保存到 ./config.yaml。

        文件不存在则自动创建（包括父目录）。
        """
        import yaml

        target = Path(path) if path else Path.cwd() / "config.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)

        data = self.model_dump(exclude_none=True)
        with open(target, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        return target


def _load_dotenv():
    """尝试加载 .env 文件到 os.environ（失败不报错，因为 .env 是可选的）。"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
