# Minimal SWE Agent

基于 LangGraph + Agno 的多智能体软件工程助手，覆盖任务规划、工具调用、记忆管理和技能扩展。

## 架构

```
                         ┌──────────────────────────────────────┐
                         │            Master (LLM)              │
                         │   任务拆解 · 规划 · 路由决策           │
                         └──────────────────┬───────────────────┘
                                            │ PLAN / NEXT / TASK
                                            ▼
                         ┌──────────────────────────────────────┐
                         │              Router                   │
                         └──────┬───────────┬───────────┬───────┘
                                │           │           │
                    ┌───────────┘           │           └───────────┐
                    ▼                       ▼                       ▼
           ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
           │  Bash Worker │        │  File Worker │        │Search Worker │
           │   (shell)    │        │  (r/w/e)     │        │ (grep/glob)  │
           └──────┬───────┘        └──────┬───────┘        └──────┬───────┘
                  │                       │                       │
                  └───────────────────────┼───────────────────────┘
                                          ▼
                         ┌──────────────────────────────────────┐
                         │          Aggregator (LLM)            │
                         │  结果汇总 · 记忆存盘 · 迭代判断        │
                         └──────────────────┬───────────────────┘
                                            │
                          ┌─────────────────┴─────────────────┐
                          ▼                                   ▼
                    (回 Master)                             END
```

**执行循环**：Master 拆解任务 → Router 分配 Worker → Worker 执行工具 → Aggregator 汇总结果 → 判断继续迭代或结束。

## 技术栈

| 层级 | 组件 | 用途 |
|------|------|------|
| Agent 编排 | **LangGraph** | 状态图构建、条件路由、流式执行 |
| Agent 框架 | **Agno** | Master/Worker Agent 创建与 LLM 工具调用循环 |
| LLM 网关 | **LiteLLM** | 统一 100+ LLM 供应商接口 |
| 记忆系统 | **mem0 + Qdrant + fastembed** | 长期对话记忆，语义检索，会话压缩 |
| 工具协议 | **MCP** | 外部工具服务器扩展（stdio/sse/http） |
| 技能系统 | **Agent Skills** | 领域知识注入，Markdown 定义 |
| CLI 交互 | **prompt-toolkit** | 补全、历史、快捷键 |

## 快速开始

```bash
# 安装
git clone https://github.com/AAAGryMt/Minimal-SWE-Agent.git
cd minimal-swe-agent
uv sync

# 配置（二选一）
cp .env.example .env          # 环境变量方式
# 或编辑 config.yaml          # 配置文件方式

# 启动
uv run swe-agent              # 交互式 REPL
uv run swe-agent -t "任务"    # 单次执行
```

## 配置方式

优先级：`REPL /config` > `CLI --model` > `.env` > `config.yaml` > 默认值

```bash
# CLI 参数覆盖
swe-agent -m gpt-4o -k sk-xxx -b https://api.openai.com

# REPL 内切换
/config model gpt-4o
/config key sk-new
/config base https://api.deepseek.com
```

## 项目结构

```
src/swe_agent/
├── cli/                  # CLI 入口与交互
│   ├── main.py           # 参数解析，模式分发
│   ├── loop.py           # 交互式 REPL / 单次执行
│   ├── runner.py         # Agent 图构建与流式渲染
│   └── display.py        # 终端彩色输出
├── agent/                # 多 Agent 编排
│   ├── graph.py          # LangGraph 拓扑定义
│   ├── nodes.py          # 节点函数（Master/Worker/Aggregator/Router）
│   ├── factory.py        # Agno Agent 工厂
│   ├── state.py          # AgentState 类型
│   └── registry.py       # Worker 注册表
├── tools/                # 工具实现
│   ├── bash_tool.py      # Shell 命令执行
│   ├── file_tools.py     # 文件读写编辑
│   ├── search_grep.py    # ripgrep 内容搜索
│   ├── search_glob.py    # Glob 文件匹配
│   ├── skill_loader.py   # Skill 加载与发现
│   ├── skill_tool.py     # Skill Agent 工具
│   ├── mcp_loader.py     # MCP 协议工具加载
│   └── security.py       # 路径安全检查
├── core/                 # 核心抽象
│   ├── tool.py           # BaseTool / ToolResult
│   └── memory_manager.py # mem0 封装
└── config.py             # Pydantic 配置模型
```
