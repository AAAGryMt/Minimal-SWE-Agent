"""Terminal rendering utilities for the CLI."""

import re
import uuid
from datetime import datetime

from swe_agent.config import Config


class Color:
    """ANSI 转义序列颜色常量，用于终端彩色文本输出。"""

    # 样式控制 
    RESET = "\033[0m"       # 重置所有属性
    BOLD = "\033[1m"        # 粗体/高亮
    DIM = "\033[2m"         # 暗淡（灰色）

    # 标准前景色（30-37）
    RED = "\033[31m"        # 红色
    GREEN = "\033[32m"      # 绿色
    YELLOW = "\033[33m"     # 黄色
    BLUE = "\033[34m"       # 蓝色
    CYAN = "\033[36m"       # 青色
    WHITE = "\033[37m"      # 白色

    # 明亮前景色（90-97）
    BRIGHT_GREEN = "\033[92m"   # 亮绿
    BRIGHT_YELLOW = "\033[93m"  # 亮黄
    BRIGHT_BLUE = "\033[94m"    # 亮蓝
    BRIGHT_CYAN = "\033[96m"    # 亮青


def _display_width(s: str) -> int:
    """计算去除 ANSI 转义序列后的字符串实际显示宽度"""
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def print_banner() -> None:
    """在终端打印应用启动横幅"""
    box = 56
    text = f"{Color.BOLD}Minimal SWE Agent{Color.RESET}"
    text_w = _display_width(text)
    pad = box - 2 - text_w
    left = pad // 2
    right = pad - left
    print()
    print(f"{Color.BOLD}{Color.BRIGHT_BLUE}╔{'═' * box}╗{Color.RESET}")
    print(f"{Color.BOLD}{Color.BRIGHT_BLUE}║{Color.RESET} {' ' * left}{text}{' ' * right} {Color.BOLD}{Color.BRIGHT_BLUE}║{Color.RESET}")
    print(f"{Color.BOLD}{Color.BRIGHT_BLUE}╚{'═' * box}╝{Color.RESET}")
    print()


def _info_line(text: str, box: int = 56) -> None:
    """在终端打印单行信息文本，两侧用暗色竖线包裹"""
    w = _display_width(text)
    pad = max(0, box - 1 - w)
    print(f"{Color.DIM}│{Color.RESET} {text}{' ' * pad}{Color.DIM}│{Color.RESET}")


def print_session_info(config: Config) -> None:
    """在终端打印会话信息框"""
    box = 56
    print(f"{Color.DIM}┌{'─' * box}┐{Color.RESET}")
    header = f"{Color.BRIGHT_CYAN}Session Info{Color.RESET}"
    hw = _display_width(header)
    hp = (box - 1 - hw) // 2
    print(f"{Color.DIM}│{Color.RESET} {' ' * hp}{header}{' ' * (box - 1 - hw - hp)}{Color.DIM}│{Color.RESET}")
    print(f"{Color.DIM}├{'─' * box}┤{Color.RESET}")
    _info_line(f"Model: {config.llm.model}")
    _info_line(f"Workspace: {config.agent.workspace_dir}")
    _info_line(f"Session ID: {uuid.uuid4().hex[:8]}")
    print(f"{Color.DIM}└{'─' * box}┘{Color.RESET}")
    print()


def print_load_tools() -> None:
    """打印已加载的工具列表及其启用状态"""
    tools_info: list[tuple[str, bool]] = [
        ("bash", True),
        ("file_tools (read/write/edit)", True),
        ("grep", True),
        ("glob", True),
    ]
    for name, enabled in tools_info:
        icon = f"{Color.GREEN}✅{Color.RESET}" if enabled else f"{Color.YELLOW}⚠️{Color.RESET}"
        print(f"  {icon} Loaded {name}")
    print()


def print_help() -> None:
    """打印帮助信息，列出所有可用的交互命令及其说明，以及基本使用提示"""
    text = f"""
{Color.BOLD}{Color.BRIGHT_YELLOW}Commands:{Color.RESET}
  {Color.BRIGHT_GREEN}/help{Color.RESET}        - Show this help
  {Color.BRIGHT_GREEN}/clear{Color.RESET}       - Clear screen
  {Color.BRIGHT_GREEN}/exit{Color.RESET}        - Exit (also: exit, quit, q)
  {Color.BRIGHT_GREEN}/compact{Color.RESET}     - Compress session context via LLM
  {Color.BRIGHT_GREEN}/prompt <text>{Color.RESET} - Set custom system prompt
  {Color.BRIGHT_GREEN}/prompt{Color.RESET}       - Show current system prompt
  {Color.BRIGHT_GREEN}/prompt reset{Color.RESET} - Reset to default system prompt
  {Color.BRIGHT_GREEN}/memory{Color.RESET}       - Show memory stats
  {Color.BRIGHT_GREEN}/memory clear{Color.RESET} - Clear all session memories

{Color.BOLD}{Color.BRIGHT_YELLOW}Usage:{Color.RESET}
  Enter your task directly. Agent will plan, execute tools, and respond.
  Use {Color.BRIGHT_CYAN}Ctrl+C{Color.RESET} to exit, {Color.BRIGHT_CYAN}Ctrl+U{Color.RESET} to clear input.
"""
    print(text)


def _fmt_tokens(n: int) -> str:
    """将 token 数量格式化"""
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)


def print_turn_stats(duration_s: float, tool_count: int, msg_count: int, tokens: int = 0, context_msgs: int = 0) -> None:
    """打印单轮 Agent 交互的统计信息"""
    m, s = divmod(int(duration_s), 60)
    print()
    print(f"{Color.BOLD}{Color.BRIGHT_CYAN}Turn Statistics:{Color.RESET}")
    print(f"{Color.DIM}{'─' * 52}{Color.RESET}")
    print(f"  Duration: {m:02d}:{s:02d}")
    print(f"  Messages: {msg_count}")
    print(f"  Tool Calls: {tool_count}")
    print(f"  Tokens: {_fmt_tokens(tokens)}")
    print(f"  Context Messages: {context_msgs}")
    print(f"{Color.DIM}{'─' * 52}{Color.RESET}")


def print_session_stats(turns: int, start: datetime) -> None:
    """打印整个会话的统计信息，包括总耗时和 Agent 执行轮数"""
    duration = datetime.now() - start
    m, s = divmod(int(duration.total_seconds()), 60)
    print(f"\n{Color.BOLD}{Color.BRIGHT_CYAN}Session Stats:{Color.RESET}")
    print(f"{Color.DIM}{'─' * 40}{Color.RESET}")
    print(f"  Duration: {m:02d}:{s:02d}")
    print(f"  Agent turns: {turns}")
    print(f"{Color.DIM}{'─' * 40}{Color.RESET}")