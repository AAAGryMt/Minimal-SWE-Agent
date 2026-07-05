"""CLI entry point — argument parsing and mode dispatch."""

import argparse
import asyncio
from pathlib import Path

from swe_agent.config import Config
from swe_agent.cli.loop import interactive_loop, run_once


def parse_args() -> argparse.Namespace:
    # 可选参数：任务文本、工作目录、用户 ID、LLM 覆盖
    parser = argparse.ArgumentParser(description="Minimal SWE Agent")
    parser.add_argument("--task", "-t", type=str, default=None, help="Execute a task and exit")
    parser.add_argument("--workspace", "-w", type=str, default=None, help="Workspace directory")
    parser.add_argument("--user-id", type=str, default=None, help="User ID for memory isolation")
    parser.add_argument("--model", "-m", type=str, default=None, help="Override LLM model (e.g. gpt-4o)")
    parser.add_argument("--api-key", "-k", type=str, default=None, help="Override LLM API key")
    parser.add_argument("--api-base", "-b", type=str, default=None, help="Override LLM API base URL")
    return parser.parse_args()


def main():
    # 1) 解析参数并加载配置（YAML → .env → CLI 覆盖）
    args = parse_args()
    config = Config.load()
    config.apply_cli_overrides(model=args.model, api_key=args.api_key, api_base=args.api_base)

    if args.workspace:
        config.agent.workspace_dir = str(Path(args.workspace).expanduser().absolute())

    # 2) 按模式分发：有 --task 则单次执行，否则进入交互 REPL
    if args.task:
        asyncio.run(run_once(args.task, config, cli_user_id=args.user_id))
    else:
        asyncio.run(interactive_loop(config, cli_user_id=args.user_id))
