---
name: "example-skill"
description: "Example skill demonstrating the SKILL.md format with YAML frontmatter"
---

# Example Skill

This is an example skill file. Each skill is a directory containing a `SKILL.md` file.

## Usage

When the agent needs to use this skill, it calls the `get_skill` tool with the skill name `example-skill`.

## Structure

```
skills/
└── example-skill/
    └── SKILL.md
```

Each skill directory can contain additional resource files referenced from the SKILL.md.
