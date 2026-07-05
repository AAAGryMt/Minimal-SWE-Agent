from __future__ import annotations

from typing import Any

from swe_agent.core.tool import BaseTool, ToolResult
from swe_agent.tools.skill_loader import SkillLoader


class GetSkillTool(BaseTool):
    def __init__(self, skill_loader: SkillLoader):
        self.skill_loader = skill_loader

    @property
    def name(self) -> str:
        return "get_skill"

    @property
    def description(self) -> str:
        return "Get complete content and guidance for a specified skill, used for executing specific types of tasks"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to retrieve",
                }
            },
            "required": ["skill_name"],
        }

    async def execute(self, skill_name: str) -> ToolResult:
        skill = self.skill_loader.get_skill(skill_name)
        if not skill:
            available = ", ".join(self.skill_loader.list_skills())
            return ToolResult(
                success=False,
                content="",
                error=f"Skill '{skill_name}' not found. Available: {available}",
            )
        return ToolResult(success=True, content=skill.to_prompt())
