"""LangGraph 节点函数 —— Master / Workers / Aggregator / Router 的业务逻辑。"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from langchain_core.messages import AIMessage

from swe_agent.agent.state import AgentState
from swe_agent.agent.factory import AgentFactory
from swe_agent.agent.registry import NEXT_AGENTS, WORKER_NAMES


# AgentFactory 上 create_{worker_name} 方法的延迟引用，避免循环导入
_WORKER_CREATORS = {
    name: getattr(AgentFactory, f"create_{name}")
    for name in WORKER_NAMES
}


def _parse_master_output(content: str) -> tuple[str, str, str]:
    """从 Master 的 LLM 输出中提取 PLAN / NEXT / TASK 三个字段。

    Master 的输出格式约定：
        PLAN: <brief plan>
        NEXT: <worker_name | __end__>
        TASK: <task description>
    """
    plan = re.search(r"PLAN:\s*(.+?)(?:\n|$)", content)
    next_ = re.search(r"NEXT:\s*(\S+)", content)
    task = re.search(r"TASK:\s*(.+?)(?:\n|$)", content)
    return (
        plan.group(1).strip() if plan else "",
        next_.group(1).strip() if next_ else "aggregator",
        task.group(1).strip() if task else "",
    )


async def _store_state_messages(state: AgentState, factory: AgentFactory) -> int:
    """将 state 中新增的消息增量存入 mem0 记忆，避免重复存储。

    通过 _stored_msg_count 追踪已存消息数，只处理 [prev_count:] 切片。
    返回当前消息总数，供调用方更新 _stored_msg_count。
    """
    mm = factory.memory_manager
    if not mm or not mm.enabled:
        return state.get("_stored_msg_count", 0)
    user_id = state.get("user_id", "default")
    session_id = state.get("session_id", "default")
    messages = state.get("messages", [])
    prev_count = state.get("_stored_msg_count", 0)
    new_msgs = []
    for msg in messages[prev_count:]:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", "")
        if content:
            new_msgs.append((role, str(content)))

    def _store():
        for role, content in new_msgs:
            mm.store_interaction(
                user_id=user_id,
                session_id=session_id,
                role=role,
                content=content,
            )

    if new_msgs:
        await asyncio.to_thread(_store)
    return len(messages)


async def _run_worker(
    state: AgentState,
    factory: AgentFactory,
    worker_name: str,
) -> dict[str, Any]:
    # 1) 通过工厂创建 Agno Agent 实例（携带对应工具集）
    try:
        create_fn = _WORKER_CREATORS.get(worker_name)
        if not create_fn:
            raise ValueError(f"Unknown worker: {worker_name}")
        agent = create_fn(factory)

        # 2) 组装上下文 prompt：任务 + 计划 + 对话历史 + 记忆
        context_parts = [f"Task: {state['task']}"]
        if state.get("plan"):
            context_parts.insert(0, f"Plan: {state['plan']}")
        messages = state.get("messages", [])
        if messages:
            history_lines = []
            for m in messages:
                role = getattr(m, "type", "unknown")
                content = getattr(m, "content", "")
                if content:
                    history_lines.append(f"[{role}]: {str(content)[:500]}")
            if history_lines:
                context_parts.append("Conversation history:\n" + "\n".join(history_lines[-5:]))

        memory_context = state.get("memory_context", "")
        if memory_context:
            context_parts.append(f"Relevant context:\n{memory_context}")

        # 3) 调用 Agno Agent 执行（含工具调用循环）
        prompt = "\n\n".join(context_parts)
        result = await agent.arun(prompt)
        m = getattr(result, "metrics", None)
        tokens = (m.input_tokens + m.output_tokens) if m else 0
        return {
            "messages": [AIMessage(content=result.content or "")],
            "_tokens": tokens,
        }
    except Exception as e:
        error_msg = f"Error in {worker_name}: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "_tokens": 0,
        }


async def master_node(state: AgentState, factory: AgentFactory) -> dict[str, Any]:
    # 1) 迭代上限检查：超出后跳过 LLM，直接转 Aggregator
    iteration = state.get("iteration", 0) + 1
    max_iter = getattr(factory, "max_iterations", 10) or 10
    if iteration > max_iter:
        return {
            "messages": [AIMessage(content="Maximum iterations reached.")],
            "plan": state.get("plan"),
            "next_agent": "aggregator",
            "task": state.get("task", ""),
            "iteration": iteration,
            "_tokens": 0,
            "_done": True,
        }
    try:
        # 2) 创建 Master Agent（纯推理，无工具）
        memory_context = state.get("memory_context", "") or ""
        system_prompt = state.get("system_prompt", "") or None

        agent = factory.create_master(
            memory_context=memory_context,
            system_prompt=system_prompt,
        )

        # 3) 组装上下文：原始任务 + 上次计划 + 近期对话
        context_parts = [f"Original task: {state['task']}"]
        if state.get("plan"):
            context_parts.append(f"Previous plan: {state['plan']}")
        messages = state.get("messages", [])
        if len(messages) > 1:
            history_lines = []
            for m in messages:
                role = getattr(m, "type", "unknown")
                content = getattr(m, "content", "")
                if content:
                    history_lines.append(f"[{role}]: {str(content)[:600]}")
            context_parts.append("Conversation so far:\n" + "\n".join(history_lines[-8:]))

        # 4) LLM 推理并解析结构化输出
        prompt = "\n\n".join(context_parts)
        result = await agent.arun(prompt)
        m = getattr(result, "metrics", None)
        tokens = (m.input_tokens + m.output_tokens) if m else 0
        content = result.content or ""

        plan, next_agent, task_desc = _parse_master_output(content)
        if next_agent not in NEXT_AGENTS:
            next_agent = "aggregator"

        # 5) LLM 说 __end__ 则标记完成，但仍走 aggregator 出汇总
        done = next_agent == "__end__"
        if done:
            next_agent = "aggregator"

        return {
            "messages": [AIMessage(content=content)],
            "plan": plan or state.get("plan"),
            "next_agent": next_agent,
            "task": task_desc or state["task"],
            "iteration": iteration,
            "_tokens": tokens,
            "_done": done,
        }
    except Exception as e:
        error_msg = f"Error in master: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "plan": state.get("plan"),
            "next_agent": "aggregator",
            "task": state.get("task", ""),
            "iteration": iteration,
            "_tokens": 0,
            "_done": False,
        }


# 三个 Worker 节点 —— 统一委托给 _run_worker
async def bash_worker_node(state: AgentState, factory: AgentFactory) -> dict[str, Any]:
    return await _run_worker(state, factory, "bash_worker")


async def file_worker_node(state: AgentState, factory: AgentFactory) -> dict[str, Any]:
    return await _run_worker(state, factory, "file_worker")


async def search_worker_node(state: AgentState, factory: AgentFactory) -> dict[str, Any]:
    return await _run_worker(state, factory, "search_worker")


async def aggregator_node(state: AgentState, factory: AgentFactory) -> dict[str, Any]:
    try:
        # 1) 复用 Master 的 LLM Agent 做汇总推理
        memory_context = state.get("memory_context", "") or ""
        system_prompt = state.get("system_prompt", "") or None

        agent = factory.create_master(
            memory_context=memory_context,
            system_prompt=system_prompt,
        )
        # 2) 将全部对话历史拼接成汇总 prompt
        summary_prompt = (
            f"Summarize the results of the following task:\n\n"
            f"Original task: {state.get('task', '')}\n"
            f"Plan: {state.get('plan', '')}\n\n"
            f"Conversation so far:\n"
        )
        for msg in state.get("messages", []):
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "")
            summary_prompt += f"\n[{role}]: {str(content)[:1000]}"

        summary_prompt += "\n\nProvide a clear final summary for the user."
        result = await agent.arun(summary_prompt)
        m = getattr(result, "metrics", None)
        tokens = (m.input_tokens + m.output_tokens) if m else 0
        final = result.content or ""

        # 3) 增量存储消息到 mem0
        stored_count = await _store_state_messages(state, factory)
        # 4) 单独存储最终汇总
        if final:
            mm = factory.memory_manager
            if mm and mm.enabled:
                await asyncio.to_thread(
                    mm.store_interaction,
                    user_id=state.get("user_id", "default"),
                    session_id=state.get("session_id", "default"),
                    role="assistant",
                    content=final,
                )

        # 5) 根据 _done 标志决定是结束还是回到 Master
        done = state.get("_done", False)
        return {
            "final_response": final,
            "next_agent": "__end__" if done else "master",
            "_tokens": tokens,
            "_stored_msg_count": stored_count,
        }
    except Exception as e:
        error_msg = f"Error in aggregator: {str(e)}"
        return {
            "final_response": error_msg,
            "next_agent": "master",
            "_tokens": 0,
            "_stored_msg_count": state.get("_stored_msg_count", 0),
        }


def router_node(state: AgentState) -> str:
    """纯路由函数：读取 state.next_agent 返回下一个节点名。"""
    return state.get("next_agent", "aggregator")
