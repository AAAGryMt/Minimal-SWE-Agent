"""Interactive REPL and one-shot execution modes."""

import uuid
from datetime import datetime
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from swe_agent.config import Config
from swe_agent.core.memory_manager import MemoryManager
from swe_agent.cli.display import (
    Color,
    print_banner,
    print_session_info,
    print_load_tools,
    print_help,
    print_turn_stats,
    print_session_stats,
)
from swe_agent.cli.runner import run_agent


def _print_config_help():
    print(f"""
{Color.BRIGHT_BLUE}/config ── Usage{Color.RESET}
  /config                        查看当前配置
  /config model <name>           设置 LLM 模型
  /config key <api_key>          设置 API Key
  /config base <url>             设置 API Base URL
  /config max_tokens <n>         设置最大 token 数
  /config temperature <0-2>      设置采样温度

{Color.DIM}修改后自动保存到 ./config.yaml{Color.RESET}
""")


async def interactive_loop(config: Config, cli_user_id: str | None = None):
    # 1) 初始化 prompt_toolkit：补全、样式、Ctrl+U 清空、历史持久化
    completer = WordCompleter(["/help", "/clear", "/exit", "/compact", "/prompt", "/memory", "/config"], ignore_case=True)
    prompt_style = Style.from_dict({"prompt": "#3fb950 bold"})
    kb = KeyBindings()

    # Ctrl+U 清空当前输入
    @kb.add("c-u")
    def _(event):
        event.current_buffer.reset()

    # 历史文件：~/.minimal-swe-agent/.history
    history_file = Path.home() / ".minimal-swe-agent" / ".history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    session = PromptSession(
        history=FileHistory(str(history_file)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
        style=prompt_style,
        key_bindings=kb,
    )

    # 2) 初始化记忆管理器与会话 ID
    memory_manager = MemoryManager(
        memory_config=config.memory,
        llm_config=config.llm,
    )

    user_id = cli_user_id or "default"
    session_id = str(uuid.uuid4())

    # 3) 打印启动信息
    if memory_manager.system_prompt:
        print(f"{Color.DIM}Loaded custom system prompt.{Color.RESET}")

    print_banner()
    print_session_info(config)
    print_load_tools()
    print(f"{Color.DIM}Type {Color.BRIGHT_GREEN}/help{Color.DIM} for help, {Color.BRIGHT_GREEN}/exit{Color.DIM} to quit{Color.RESET}")
    print()

    session_start = datetime.now()
    agent_turns = 0

    # 4) REPL 主循环
    while True:
        try:
            user_input = await session.prompt_async(
                [("class:prompt", "You"), ("", " › ")],
                multiline=False,
            )
            user_input = user_input.strip()
            if not user_input:
                continue

            # 4a) 处理 / 命令：exit / help / clear / compact / prompt / memory
            if user_input.startswith("/"):
                cmd = user_input.lower()
                if cmd in ("/exit", "/quit", "/q"):
                    break
                elif cmd == "/help":
                    print_help()
                    continue
                elif cmd == "/clear":
                    print("\033[2J\033[H", end="")
                    continue
                elif cmd == "/compact":
                    print(f"\n{Color.BRIGHT_BLUE}Compacting session context...{Color.RESET}")
                    summary = await memory_manager.compact_session(
                        user_id=user_id,
                        session_id=session_id,
                    )
                    print(f"{Color.GREEN}Compact complete.{Color.RESET}")
                    print(f"  {Color.DIM}Summary: {summary[:300]}{'...' if len(summary) > 300 else ''}{Color.RESET}")
                    print()
                    continue
                elif cmd.startswith("/prompt"):
                    parts = user_input[len("/prompt"):].strip()
                    if not parts:
                        current = memory_manager.system_prompt
                        if current:
                            print(f"\n{Color.BRIGHT_BLUE}Current system prompt:{Color.RESET}")
                            print(f"  {current}\n")
                        else:
                            print(f"\n{Color.DIM}No custom system prompt set.{Color.RESET}\n")
                    elif parts == "reset":
                        memory_manager.set_system_prompt(None)
                        print(f"\n{Color.GREEN}System prompt reset to default.{Color.RESET}\n")
                    else:
                        memory_manager.set_system_prompt(parts)
                        print(f"\n{Color.GREEN}System prompt set.{Color.RESET}\n")
                    continue
                elif cmd.startswith("/memory"):
                    parts = user_input[len("/memory"):].strip()
                    if parts == "clear":
                        memory_manager.clear_session(user_id=user_id, session_id=session_id)
                        print(f"\n{Color.GREEN}Session memories cleared.{Color.RESET}\n")
                    else:
                        cnt = memory_manager.get_memory_count(user_id=user_id, session_id=session_id)
                        total = memory_manager.get_memory_count(user_id=user_id)
                        print(f"\n{Color.BRIGHT_BLUE}Memory stats:{Color.RESET}")
                        print(f"  Session memories: {cnt}")
                        print(f"  Total memories (user): {total}\n")
                    continue
                elif cmd.startswith("/config"):
                    parts = user_input[len("/config"):].strip()
                    if not parts:
                        _print_config_help()
                        key = config.llm.api_key
                        masked = "****" + key[-4:] if key and len(key) > 4 else "(not set)"
                        print(f"{Color.BRIGHT_BLUE}LLM Configuration:{Color.RESET}")
                        print(f"  model:       {config.llm.model}")
                        print(f"  api_key:     {masked}")
                        print(f"  api_base:    {config.llm.api_base or '(default)'}")
                        print(f"  max_tokens:  {config.llm.max_tokens or '(unlimited)'}")
                        print(f"  temperature: {config.llm.temperature}")
                        print()
                    else:
                        sub = parts.split(None, 1)
                        sub_cmd = sub[0].lower()
                        sub_val = sub[1] if len(sub) > 1 else ""

                        set_fields = {"model", "key", "base", "max_tokens", "temperature"}
                        if sub_cmd not in set_fields or not sub_val:
                            _print_config_help()
                            continue

                        if sub_cmd == "model":
                            config.llm.model = sub_val
                        elif sub_cmd == "key":
                            config.llm.api_key = sub_val
                        elif sub_cmd == "base":
                            config.llm.api_base = sub_val
                        elif sub_cmd == "max_tokens":
                            try:
                                config.llm.max_tokens = int(sub_val)
                            except ValueError:
                                print(f"\n{Color.YELLOW}max_tokens 必须是整数: {sub_val}{Color.RESET}\n")
                                continue
                        elif sub_cmd == "temperature":
                            try:
                                config.llm.temperature = float(sub_val)
                            except ValueError:
                                print(f"\n{Color.YELLOW}temperature 必须是数字: {sub_val}{Color.RESET}\n")
                                continue

                        saved_path = config.save()
                        print(f"\n{Color.GREEN}{sub_cmd} 已设置 → 已保存到 {saved_path}{Color.RESET}\n")
                    continue
                else:
                    print(f"{Color.RED}Unknown: {user_input}{Color.RESET}")
                    continue

            # 4b) 普通输入 exit/quit/q 退出
            if user_input.lower() in ("exit", "quit", "q"):
                break

            print()
            print(f"{Color.DIM}{'─' * 60}{Color.RESET}")
            print()

            # 4c) 存储用户输入到记忆，检索相关历史上下文
            if memory_manager.enabled:
                memory_manager.store_interaction(
                    user_id=user_id,
                    session_id=session_id,
                    role="user",
                    content=user_input,
                )
                memory_context = memory_manager.get_context(
                    user_id=user_id,
                    query=user_input,
                )
            else:
                memory_context = ""

            # 4d) 调用 Agent 执行，累加回合数，打印统计
            system_prompt = memory_manager.system_prompt

            final, tool_count, msg_count, duration, tokens, ctx_msgs = await run_agent(
                task=user_input,
                config=config,
                memory_manager=memory_manager,
                user_id=user_id,
                memory_context=memory_context,
                system_prompt=system_prompt,
                session_id=session_id,
            )
            agent_turns += 1
            print_turn_stats(duration, tool_count, msg_count, tokens, ctx_msgs)
            print(f"\n{Color.DIM}{'─' * 60}{Color.RESET}\n")

        except KeyboardInterrupt:
            break

    # 5) 退出：打印会话统计
    print_session_stats(agent_turns, session_start)
    print(f"{Color.BRIGHT_GREEN}Bye!{Color.RESET}\n")


async def run_once(task: str, config: Config, cli_user_id: str | None = None):
    # 1) 初始化记忆上下文
    memory_manager = MemoryManager(
        memory_config=config.memory,
        llm_config=config.llm,
    )
    user_id = cli_user_id or "default"
    session_id = str(uuid.uuid4())
    memory_context = memory_manager.get_context(user_id=user_id, query=task) if memory_manager.enabled else ""
    system_prompt = memory_manager.system_prompt

    # 2) 单次执行 + 统计打印
    print(f"\n{Color.DIM}Task: {task}{Color.RESET}\n")
    final, tool_count, msg_count, duration, tokens, ctx_msgs = await run_agent(
        task=task,
        config=config,
        memory_manager=memory_manager,
        user_id=user_id,
        memory_context=memory_context,
        system_prompt=system_prompt,
        session_id=session_id,
    )
    print_turn_stats(duration, tool_count, msg_count, tokens, ctx_msgs)
    print()
