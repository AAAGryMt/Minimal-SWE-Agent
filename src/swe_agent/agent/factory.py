"""Agent 工厂 —— 创建 Master（规划者）和三个 Worker（执行者）的 Agno Agent 实例。"""

from agno.agent import Agent
from agno.models.litellm import LiteLLM

from swe_agent.config import Config
from swe_agent.core.memory_manager import MemoryManager
from swe_agent.core.tool import BaseTool
from swe_agent.tools.skill_loader import SkillLoader


class AgentFactory:
    def __init__(
        self,
        config: Config | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        workspace_dir: str | None = None,
        max_iterations: int | None = None,
        memory_manager: MemoryManager | None = None,
        mcp_tools: list[BaseTool] | None = None,
        skill_loader: SkillLoader | None = None,
    ):
        # 存储 config 引用：_make_model() 会动态读取 config.llm.*，使得 /config 命令即时生效
        self._config = config
        # 构造参数覆盖（传了则固定使用，不传则走 config 实时值）
        self._model_override = model
        self._api_key_override = api_key
        self._api_base_override = api_base
        self._max_tokens_override = max_tokens
        self._temperature_override = temperature if temperature is not None else None
        self._max_iterations = max_iterations or (config.agent.max_iterations if config else 10)
        self.workspace_dir = workspace_dir or "."
        self.memory_manager = memory_manager
        self.mcp_tools = mcp_tools or []
        self.skill_loader = skill_loader

    @property
    def max_iterations(self) -> int:
        return self._max_iterations

    def _make_model(self) -> LiteLLM:
        """构建 LiteLLM 模型实例：构造参数 > config.llm 实时值 > 硬编码默认值。"""
        if self._config:
            llm = self._config.llm
            model = self._model_override or llm.model
            api_key = self._api_key_override or llm.api_key
            api_base = self._api_base_override or llm.api_base
            max_tokens = self._max_tokens_override or llm.max_tokens
            temperature = self._temperature_override if self._temperature_override is not None else llm.temperature
        else:
            model = self._model_override or "deepseek-v4-flash"
            api_key = self._api_key_override
            api_base = self._api_base_override
            max_tokens = self._max_tokens_override
            temperature = self._temperature_override
        kwargs: dict = {"id": model}
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        return LiteLLM(**kwargs)

    async def _run_tool(self, tool, **kwargs) -> str:
        """统一工具调用入口：执行 BaseTool.execute 并返回内容或错误。"""
        result = await tool.execute(**kwargs)
        if result.success:
            return result.content
        return f"Error: {result.error}"

    def _get_mcp_tool_fns(self) -> list:
        """将 MCP 工具列表包装为 Agno 兼容的 async 工具函数列表。"""
        if not self.mcp_tools:
            return []

        def _make_mcp_fn(tool: BaseTool):
            async def mcp_fn(**kwargs):
                result = await tool.execute(**kwargs)
                return result.content if result.success else f"Error: {result.error}"
            mcp_fn.__name__ = tool.name
            mcp_fn.__doc__ = tool.description
            return mcp_fn

        return [_make_mcp_fn(t) for t in self.mcp_tools]

    def create_master(self, memory_context: str = "", system_prompt: str | None = None) -> Agent:
        """创建 Master Agent —— 纯推理角色，不携带任何工具。

        负责：分析任务 → 制定计划 → 路由到合适的 Worker。
        """
        instructions = system_prompt or "You are a master planning agent for a software engineering assistant."
        if memory_context:
            instructions += f"\n\nRelevant context from past sessions:\n{memory_context}\n"

        return Agent(
            model=self._make_model(),
            name="master",
            instructions=instructions,
            markdown=True,
        )

    def create_bash_worker(self) -> Agent:
        """创建 Bash Worker —— 执行 shell 命令。"""
        from swe_agent.tools.bash_tool import BashTool

        tool = BashTool(self.workspace_dir)

        async def bash_func(command: str, timeout: int = 120) -> str:
            return await self._run_tool(tool, command=command, timeout=timeout)
        bash_func.__name__ = "bash"
        bash_func.__doc__ = tool.description

        tool_fns = [bash_func]
        instructions = "You execute bash commands. Use the bash tool to run shell commands."

        if self.mcp_tools:
            tool_fns.extend(self._get_mcp_tool_fns())
            tool_names = ", ".join(t.name for t in self.mcp_tools)
            instructions += f" Available MCP tools: {tool_names}."

        return Agent(
            model=self._make_model(),
            name="bash_worker",
            tools=tool_fns,
            tool_call_limit=10,
            instructions=instructions,
            markdown=True,
        )

    def create_file_worker(self) -> Agent:
        """创建 File Worker —— 读写编辑工作目录内的文件。"""
        from swe_agent.tools.file_tools import ReadTool, WriteTool, EditTool

        read_tool = ReadTool(self.workspace_dir)
        write_tool = WriteTool(self.workspace_dir)
        edit_tool = EditTool(self.workspace_dir)

        async def read_func(path: str, offset: int | None = None, limit: int | None = None) -> str:
            return await self._run_tool(read_tool, path=path, offset=offset, limit=limit)
        read_func.__name__ = "read"
        read_func.__doc__ = "Read file contents. Args: path (str): File path. offset (int, optional): Starting line. limit (int, optional): Number of lines."

        async def write_func(path: str, content: str) -> str:
            return await self._run_tool(write_tool, path=path, content=content)
        write_func.__name__ = "write"
        write_func.__doc__ = "Write content to a file. Args: path (str): File path. content (str): Content to write."

        async def edit_func(path: str, old_str: str, new_str: str) -> str:
            return await self._run_tool(edit_tool, path=path, old_str=old_str, new_str=new_str)
        edit_func.__name__ = "edit"
        edit_func.__doc__ = "Edit file by replacing text. Args: path (str): File path. old_str (str): Text to find. new_str (str): Replacement text."

        tool_fns = [read_func, write_func, edit_func]
        instructions = "You handle file operations: read, write, and edit files in the workspace."

        if self.mcp_tools:
            tool_fns.extend(self._get_mcp_tool_fns())
            tool_names = ", ".join(t.name for t in self.mcp_tools)
            instructions += f" Available MCP tools: {tool_names}."

        return Agent(
            model=self._make_model(),
            name="file_worker",
            tools=tool_fns,
            tool_call_limit=10,
            instructions=instructions,
            markdown=True,
        )

    def create_search_worker(self) -> Agent:
        """创建 Search Worker —— 用 grep/glob 搜索代码库，可选扩展 Skill 和 MCP 工具。"""
        from swe_agent.tools.search_grep import GrepTool
        from swe_agent.tools.search_glob import GlobTool

        grep_tool = GrepTool(self.workspace_dir)
        glob_tool = GlobTool(self.workspace_dir)

        async def grep_func(pattern: str, include: str = "") -> str:
            return await self._run_tool(grep_tool, pattern=pattern, include=include)
        grep_func.__name__ = "grep"
        grep_func.__doc__ = "Search file contents using regex. Args: pattern (str): Regex pattern. include (str, optional): File glob filter."

        async def glob_func(pattern: str) -> str:
            return await self._run_tool(glob_tool, pattern=pattern)
        glob_func.__name__ = "glob"
        glob_func.__doc__ = "Find files matching glob pattern. Args: pattern (str): Glob pattern like **/*.py."

        tool_fns = [grep_func, glob_func]

        instructions = "You search the codebase using grep and glob to find files and patterns."

        # 可选：注入 Skill 加载工具
        if self.skill_loader:
            from swe_agent.tools.skill_tool import GetSkillTool
            skill_tool = GetSkillTool(self.skill_loader)
            async def get_skill_func(skill_name: str) -> str:
                result = await skill_tool.execute(skill_name=skill_name)
                return result.content if result.success else f"Error: {result.error}"
            get_skill_func.__name__ = "get_skill"
            get_skill_func.__doc__ = skill_tool.description
            tool_fns.append(get_skill_func)
            instructions += " Use get_skill to load specialized skill content."

        # 可选：注入 MCP 外部工具
        if self.mcp_tools:
            tool_fns.extend(self._get_mcp_tool_fns())
            tool_names = ", ".join(t.name for t in self.mcp_tools)
            instructions += f" Available MCP tools: {tool_names}."

        return Agent(
            model=self._make_model(),
            name="search_worker",
            tools=tool_fns,
            tool_call_limit=10,
            instructions=instructions,
            markdown=True,
        )
