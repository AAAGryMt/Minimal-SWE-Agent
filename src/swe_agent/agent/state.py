"""LangGraph 状态定义 —— 在整个图节点之间流转的共享字典。"""

from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # 对话历史，使用 add_messages reducer 实现累加而非覆盖
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # 当前任务描述（由 Master 的 TASK 行持续更新）
    task: str
    # 下一个要执行的节点名称，由 router_node 消费
    next_agent: str
    # Aggregator 产出的最终回复文本
    final_response: str | None
    # 当前迭代次数（仅 Master 递增）
    iteration: int
    # 唯一会话 ID，用于记忆存储隔离
    session_id: str
    # Master 生成的执行计划，跨迭代保留
    plan: str | None
    # 用户标识，用于记忆隔离
    user_id: str
    # 从 mem0 检索到的历史记忆上下文
    memory_context: str | None
    # 注入 Master 的系统提示词
    system_prompt: str | None
    # 累计 token 消耗
    _tokens: int
    # 是否已完成（Master 设为 True 后 Aggregator 读取并路由到 END）
    _done: bool
    # 已存入记忆的消息数量，避免重复存储
    _stored_msg_count: int
