"""mem0 记忆管理封装 —— 长期记忆的存储、检索、压缩和清理。

底层使用 Qdrant（本地文件模式）做向量存储 + fastembed 做 embedding + litellm 做压缩推理。
"""

from __future__ import annotations

import os
from pathlib import Path

from swe_agent.config import MemoryConfig, LLMConfig


def _extract_memories(results) -> list[dict]:
    """从 mem0 返回结果中提取记忆列表，兼容 list / dict / 空值。"""
    if isinstance(results, list):
        return results
    if isinstance(results, dict):
        return results.get("results", [])
    return []


def _get_memory_text(item: dict) -> str:
    """从单条记忆记录中提取文本内容。"""
    return item.get("memory", item.get("text", str(item)))


def _get_memory_id(item: dict) -> str:
    """从单条记忆记录中提取唯一 ID。"""
    return item.get("id", "")


class MemoryManager:
    def __init__(
        self,
        memory_config: MemoryConfig,
        llm_config: LLMConfig,
    ):
        self.config = memory_config
        self.llm_config = llm_config
        self._mem0 = None          # mem0.Memory 实例，懒加载
        self._system_prompt = memory_config.system_prompt

    def _init_env(self):
        """初始化 mem0 运行环境：禁用遥测、静默日志、设置 API Key。

        注意：此方法会修改全局 os.environ，确保 mem0 的 litellm 调用能复用凭证。
        """
        os.environ.setdefault("MEM0_TELEMETRY", "false")
        os.environ.setdefault("POSTHOG_DISABLED", "true")

        import logging
        logging.getLogger("mem0.utils.spacy_models").setLevel(logging.ERROR)
        logging.getLogger("mem0.memory.main").setLevel(logging.ERROR)
        logging.getLogger("fastembed").setLevel(logging.ERROR)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("posthog").setLevel(logging.ERROR)

        api_key = self.config.api_key or self.llm_config.api_key
        api_base = self.config.api_base or self.llm_config.api_base

        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
            model = self.config.llm_model or self.llm_config.model
            provider = model.split("/")[0] if "/" in model else "openai"
            provider_key = provider.upper() + "_API_KEY"
            os.environ[provider_key] = api_key

        if api_base:
            os.environ["OPENAI_API_BASE"] = api_base

    def _get_mem0(self):
        """懒加载 mem0.Memory 实例。

        首次调用时完成：1) 日志/环境初始化  2) 配置 Qdrant + fastembed + litellm  3) 实例化。
        """
        if self._mem0 is not None:
            return self._mem0

        self._init_env()

        embedder_model = "sentence-transformers/all-MiniLM-L6-v2"

        config: dict = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(Path(self.config.directory).expanduser() / "qdrant"),
                    "embedding_model_dims": 384,
                },
            },
            "embedder": {
                "provider": "fastembed",
                "config": {
                    "model": embedder_model,
                },
            },
            "llm": {
                "provider": "litellm",
                "config": {
                    "model": self.config.llm_model or self.llm_config.model,
                    "max_tokens": self.config.compact_max_tokens,
                },
            },
        }

        from mem0 import Memory
        self._mem0 = Memory.from_config(config)
        return self._mem0

    @property
    def enabled(self) -> bool:
        """记忆功能是否启用。"""
        return self.config.enabled

    @property
    def system_prompt(self) -> str | None:
        """用户自定义系统提示词（运行时通过 /prompt 命令设置）。"""
        return self._system_prompt

    def set_system_prompt(self, prompt: str | None):
        """设置或清空自定义系统提示词。"""
        self._system_prompt = prompt

    def store_interaction(self, user_id: str, session_id: str, role: str, content: str):
        """存储单条交互记录到 mem0 向量数据库。认证失败时降级为跳过，不崩进程。"""
        if not self.enabled:
            return
        if not content:
            return
        m = self._get_mem0()
        try:
            m.add(
                content,
                user_id=user_id,
                agent_id=role,
                metadata={"session_id": session_id, "role": role},
            )
        except Exception as e:
            error_msg = str(e)
            if "auth" in error_msg.lower() or "401" in error_msg:
                print(f"\033[33m[Memory] Skipping store: authentication failed ({error_msg[:120]})\033[0m")
            else:
                print(f"\033[33m[Memory] Skipping store: {error_msg[:120]}\033[0m")

    def get_context(self, user_id: str, query: str, limit: int = 5) -> str:
        """基于语义相似度检索与当前查询相关的历史记忆，拼接为文本返回。"""
        if not self.enabled:
            return ""
        m = self._get_mem0()
        results = _extract_memories(m.search(query, top_k=limit, filters={"user_id": user_id}))
        if not results:
            return ""
        lines = []
        for item in results:
            text = _get_memory_text(item)
            if text:
                lines.append(f"  - {text[:500]}")
        if not lines:
            return ""
        return "Relevant context from past interactions:\n" + "\n".join(lines)

    def get_session_memories(self, user_id: str, session_id: str) -> list[dict]:
        """按用户 ID 拉取全部记忆，按 session_id 过滤返回当前会话的记忆列表。"""
        if not self.enabled:
            return []
        m = self._get_mem0()
        results = _extract_memories(m.get_all(top_k=1000, filters={"user_id": user_id}))
        return [r for r in results if r.get("metadata", {}).get("session_id") == session_id]

    def clear_session(self, user_id: str, session_id: str):
        """删除指定会话的全部记忆。"""
        if not self.enabled:
            return
        memories = self.get_session_memories(user_id, session_id)
        m = self._get_mem0()
        for mem in memories:
            mem_id = _get_memory_id(mem)
            if mem_id:
                m.delete(mem_id)

    async def compact_session(self, user_id: str, session_id: str) -> str:
        """压缩会话记忆：用 LLM 生成摘要替代原始记录，减少 token 消耗。

        流程：1) 拉取会话全部记忆  2) LLM 生成密集摘要  3) 删除原始记录  4) 存回摘要。
        """
        if not self.enabled:
            return "Memory is disabled"

        memories = self.get_session_memories(user_id, session_id)
        if not memories:
            return "No memories to compact."

        texts = [_get_memory_text(m) for m in memories if _get_memory_text(m)]
        if not texts:
            return "No memories to compact."

        raw = "\n".join(f"- {t}" for t in texts)

        compact_prompt = (
            "You are a context compression assistant. Summarize the following "
            "conversation history into a concise, dense summary. "
            f"Keep it under {self.config.compact_max_tokens} tokens. "
            "Retain all key facts, decisions, preferences, and context.\n\n"
            f"History to compress:\n{raw}"
        )

        from litellm import acompletion

        model = self.config.llm_model or self.llm_config.model
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": compact_prompt}],
            "max_tokens": self.config.compact_max_tokens,
        }
        api_key = self.config.api_key or self.llm_config.api_key
        api_base = self.config.api_base or self.llm_config.api_base
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        response = await acompletion(**kwargs)
        summary = response.choices[0].message.content or ""

        self.store_interaction(
            user_id=user_id,
            session_id=session_id,
            role="system",
            content=f"[Compacted session summary]\n{summary}",
        )

        m = self._get_mem0()
        for mem in memories:
            mem_id = _get_memory_id(mem)
            if mem_id:
                m.delete(mem_id)

        return summary

    def get_memory_count(self, user_id: str, session_id: str | None = None) -> int:
        """获取记忆数量：若指定 session_id 则只统计该会话，否则统计全部。"""
        if not self.enabled:
            return 0
        if session_id:
            return len(self.get_session_memories(user_id, session_id))
        m = self._get_mem0()
        results = _extract_memories(m.get_all(top_k=1000, filters={"user_id": user_id}))
        return len(results)
