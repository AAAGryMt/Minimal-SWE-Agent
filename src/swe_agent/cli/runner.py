"""Agent execution — builds the graph and streams results."""

import uuid
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage

from swe_agent.agent.factory import AgentFactory
from swe_agent.agent.graph import build_graph
from swe_agent.agent.registry import WORKERS, WORKER_NAMES, MASTER, AGGREGATOR
from swe_agent.agent.state import AgentState
from swe_agent.config import Config
from swe_agent.core.memory_manager import MemoryManager
from swe_agent.cli.display import Color


async def run_agent(
    task: str,
    config: Config,
    memory_manager: MemoryManager | None = None,
    user_id: str = "default",
    memory_context: str = "",
    system_prompt: str | None = None,
    session_id: str | None = None,
) -> tuple[str, int, int, float, int, int]:
    # 1) 加载系统提示词：优先读取外部 SYSTEM_PROMPT.md，不存在则用硬编码兜底
    if system_prompt is None:
        sp_path = Config.find_config_file(config.agent.system_prompt_path)
        if sp_path and sp_path.exists():
            system_prompt = sp_path.read_text(encoding="utf-8")
        else:
            system_prompt = "You are a master planning agent for a software engineering assistant."

    workspace_dir = str(Path(config.agent.workspace_dir).absolute())
    system_prompt = system_prompt.replace("{WORKSPACE_DIR}", workspace_dir)

    # 2) 加载 MCP 外部工具：从 mcp.json 读取配置并初始化所有已启用的工具
    mcp_tools = []
    if config.tools.enable_mcp:
        mcp_config_path = Config.find_config_file(config.tools.mcp_config_path)
        if mcp_config_path:
            from swe_agent.tools.mcp_loader import load_mcp_tools_async

            print(f"{Color.BRIGHT_BLUE}Loading MCP tools...{Color.RESET}")
            mcp_tools = await load_mcp_tools_async(str(mcp_config_path))
            print(f"  {Color.GREEN}Loaded {len(mcp_tools)} MCP tools{Color.RESET}")
        else:
            print(f"  {Color.YELLOW}MCP config not found: {config.tools.mcp_config_path}{Color.RESET}")

    # 3) 加载 Skills 技能定义：递归扫描 skills_dir 下的 SKILL.md
    # skills_dir 查找优先级：绝对路径 > cwd > mini_agent > workspace_dir
    skill_loader = None
    if config.tools.enable_skills:
        from swe_agent.tools.skill_loader import SkillLoader

        sd = config.tools.skills_dir
        sd_path = Path(sd)
        if sd_path.is_absolute():
            skills_dir = str(sd_path)
        else:
            search_candidates = [
                Path.cwd() / sd,
                Path.cwd() / "mini_agent" / sd,
                Path(config.agent.workspace_dir) / sd,
            ]
            skills_dir = None
            for p in search_candidates:
                if p.exists():
                    skills_dir = str(p.resolve())
                    break
            if skills_dir is None:
                skills_dir = str(Path.cwd() / sd)

        skill_loader = SkillLoader(skills_dir)
        skills = skill_loader.discover_skills()
        if skills:
            print(f"{Color.GREEN}Loaded {len(skills)} skills from {skills_dir}{Color.RESET}")
            metadata = skill_loader.get_skills_metadata_prompt()
            system_prompt = system_prompt.replace("{SKILLS_METADATA}", metadata)
        else:
            print(f"  {Color.YELLOW}No skills found in {skills_dir}{Color.RESET}")
            system_prompt = system_prompt.replace("{SKILLS_METADATA}", "")
    else:
        system_prompt = system_prompt.replace("{SKILLS_METADATA}", "")

    # 4) 构建 Agent 工厂与 LangGraph 状态图
    factory = AgentFactory(
        config=config,
        memory_manager=memory_manager,
        mcp_tools=mcp_tools,
        skill_loader=skill_loader,
    )
    graph = build_graph(factory)

    # 5) 组装初始状态：将所有上下文注入图的起始节点
    initial_state: AgentState = {
        "messages": [HumanMessage(content=task)],
        "task": task,
        "next_agent": "master",
        "final_response": None,
        "iteration": 0,
        "session_id": session_id or str(uuid.uuid4()),
        "plan": None,
        "user_id": user_id,
        "memory_context": memory_context,
        "system_prompt": system_prompt,
        "_tokens": 0,
        "_done": False,
        "_stored_msg_count": 0,
    }

    # 6) 流式执行：每个 Worker 节点用不同颜色区分，实时打印 Plan/工具输出/最终结果
    worker_colors = [Color.YELLOW, Color.GREEN, Color.BLUE]
    agent_name_colors = {MASTER: Color.BLUE}
    for i, w in enumerate(WORKERS):
        agent_name_colors[w.name] = worker_colors[i % len(worker_colors)]
    agent_name_colors[AGGREGATOR] = Color.BRIGHT_BLUE

    print(f"{Color.BRIGHT_BLUE}Agent{Color.RESET} {Color.DIM}›{Color.RESET} {Color.DIM}Thinking...{Color.RESET}")
    print()

    t0 = datetime.now()
    final_response = ""
    tool_count = 0
    msg_count = 1
    total_tokens = 0
    context_msgs = 0

    # 7) 异步迭代图的状态更新流，打印每个节点的输出
    async for update in graph.astream(initial_state, stream_mode="updates"):
        for node_name, data in update.items():
            if not isinstance(data, dict):
                continue
            color = agent_name_colors.get(node_name, Color.WHITE)
            label = node_name.replace("_worker", "")

            total_tokens += data.get("_tokens") or 0

            # Master 节点：显示规划方案和下一跳路由
            if node_name == "master":
                plan = data.get("plan", "")
                next_agent = data.get("next_agent", "")
                if data.get("_tokens") or 0:
                    context_msgs = len(data.get("messages", []))
                print(f"  {color}🤔 {label}{Color.RESET}")
                if plan:
                    print(f"    {Color.DIM}Plan: {plan}{Color.RESET}")
                    print(f"    {Color.DIM}Next: {next_agent}{Color.RESET}")

            # Worker 节点：打印工具执行输出，超过 5 行则截断
            elif node_name in WORKER_NAMES:
                msgs = data.get("messages", [])
                if msgs:
                    content = getattr(msgs[-1], "content", "") or ""
                    if content:
                        tool_count += 1
                        print(f"  {color}🔧 {label}{Color.RESET}")
                        for line in content.strip().split("\n")[:5]:
                            print(f"    {Color.DIM}{line[:200]}{Color.RESET}")
                        if content.count("\n") > 5:
                            print(f"    {Color.DIM}... ({content.count(chr(10)) - 5} more lines){Color.RESET}")
                msg_count += 1

            # Aggregator 节点：输出本次任务的最终汇总
            elif node_name == "aggregator":
                final = data.get("final_response", "")
                if final:
                    final_response = final
                    msg_count += 1
                    print(f"  {Color.BRIGHT_GREEN}✅ complete{Color.RESET}")
                    print()
                    print(f"  {Color.BRIGHT_GREEN}{Color.BOLD}Result:{Color.RESET}")
                    for line in final.strip().split("\n"):
                        print(f"  {line}")

    duration = (datetime.now() - t0).total_seconds()

    # 8) 清理 MCP 连接，返回执行统计
    if config.tools.enable_mcp and mcp_tools:
        from swe_agent.tools.mcp_loader import cleanup_mcp_connections

        await cleanup_mcp_connections()

    return final_response, tool_count, msg_count, duration, total_tokens, context_msgs
