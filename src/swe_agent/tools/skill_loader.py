from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Skill:
    name: str
    description: str
    content: str
    skill_path: Path | None = None

    def to_prompt(self) -> str:
        skill_root = str(self.skill_path.parent) if self.skill_path else "unknown"
        return (
            f"# Skill: {self.name}\n\n"
            f"{self.description}\n\n"
            f"**Skill Root Directory:** `{skill_root}`\n"
            f"All files and references in this skill are relative to this directory.\n\n"
            f"---\n\n{self.content}"
        )


class SkillLoader:
    def __init__(self, skills_dir: str = "./skills"):
        self.skills_dir = Path(skills_dir)
        self.loaded_skills: dict[str, Skill] = {}

    def load_skill(self, skill_path: Path) -> Skill | None:
        try:
            content = skill_path.read_text(encoding="utf-8")

            import re
            match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
            if not match:
                return None

            fm = yaml.safe_load(match.group(1))
            body = match.group(2).strip()

            if not isinstance(fm, dict) or "name" not in fm or "description" not in fm:
                return None

            skill = Skill(
                name=fm["name"],
                description=fm["description"],
                content=body,
                skill_path=skill_path,
            )
            return skill

        except Exception:
            return None

    def discover_skills(self) -> list[Skill]:
        skills = []
        if not self.skills_dir.exists():
            return skills

        for skill_file in self.skills_dir.rglob("SKILL.md"):
            skill = self.load_skill(skill_file)
            if skill:
                skills.append(skill)
                self.loaded_skills[skill.name] = skill

        return skills

    def get_skill(self, name: str) -> Skill | None:
        return self.loaded_skills.get(name)

    def list_skills(self) -> list[str]:
        return list(self.loaded_skills.keys())

    def get_skills_metadata_prompt(self) -> str:
        if not self.loaded_skills:
            return ""

        lines = [
            "## Available Skills",
            "",
            "You have access to specialized skills for specific tasks.",
            "Load a skill's full content using the `get_skill` tool when needed.",
            "",
        ]
        for skill in self.loaded_skills.values():
            lines.append(f"- `{skill.name}`: {skill.description}")

        return "\n".join(lines)
