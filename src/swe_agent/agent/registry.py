"""Agent 注册表 —— 定义所有节点的名称常量和可用的 Worker 列表。"""

from typing import NamedTuple


class WorkerInfo(NamedTuple):
    name: str       # 节点内部标识，如 "bash_worker"
    display: str    # 展示用的短名称，如 "bash"


# 图节点名称常量
MASTER = "master"
AGGREGATOR = "aggregator"
END = "__end__"

# 三个专职 Worker：bash 命令、文件操作、代码搜索
WORKERS: list[WorkerInfo] = [
    WorkerInfo("bash_worker", "bash"),
    WorkerInfo("file_worker", "file"),
    WorkerInfo("search_worker", "search"),
]

# 派生列表：仅名称、所有合法路由目标
WORKER_NAMES = [w.name for w in WORKERS]
NEXT_AGENTS = [MASTER, *WORKER_NAMES, AGGREGATOR, END]
