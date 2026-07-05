"""LangGraph 状态图构建 —— 定义 Master → Router → Workers → Aggregator 的执行拓扑。"""

from langgraph.graph import StateGraph, END

from swe_agent.agent.state import AgentState
from swe_agent.agent.factory import AgentFactory
from swe_agent.agent.registry import WORKERS, WORKER_NAMES, MASTER, AGGREGATOR, END as END_LABEL
from swe_agent.agent.nodes import (
    master_node,
    bash_worker_node,
    file_worker_node,
    search_worker_node,
    aggregator_node,
    router_node,
)

# 节点名称 → 节点函数映射
_WORKER_NODE_FNS = {
    "bash_worker": bash_worker_node,
    "file_worker": file_worker_node,
    "search_worker": search_worker_node,
}


def build_graph(factory: AgentFactory) -> StateGraph:
    """构建并编译 LangGraph 状态图。

    拓扑：START → master → router → (worker) → aggregator → router → master/END
    所有节点通过闭包注入 factory，Workers 通过默认参数技巧避免闭包引用同一变量。
    """
    builder = StateGraph(AgentState)

    # 通过闭包将 factory 注入各节点函数
    async def _master(s):
        return await master_node(s, factory)

    async def _agg(s):
        return await aggregator_node(s, factory)

    def _router(s):
        return router_node(s)

    # 注册节点
    builder.add_node(MASTER, _master)

    for w in WORKERS:
        node_fn = _WORKER_NODE_FNS[w.name]

        # 默认参数 _fn=node_fn 在循环中立即绑定，避免闭包延迟引用
        async def _worker(s, _fn=node_fn):
            return await _fn(s, factory)

        builder.add_node(w.name, _worker)

    builder.add_node(AGGREGATOR, _agg)

    # 入口
    builder.set_entry_point(MASTER)

    # 路由表：节点返回值 → 图节点或 END
    route_map = {MASTER: MASTER}
    for w in WORKERS:
        route_map[w.name] = w.name
    route_map[AGGREGATOR] = AGGREGATOR
    route_map[END_LABEL] = END

    # 边：Master 通过 router 条件分发
    builder.add_conditional_edges(MASTER, _router, route_map)

    # 边：所有 Worker 完成后直连 Aggregator
    for w in WORKERS:
        builder.add_edge(w.name, AGGREGATOR)

    # 边：Aggregator 通过 router 决定继续（回 Master）或结束
    builder.add_conditional_edges(AGGREGATOR, _router, route_map)

    return builder.compile()
