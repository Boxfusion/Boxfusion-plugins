# Boxfusion Plugins

This repository contains Claude Code plugins and skills for Shesha framework development.

## Repository Structure

```
plugins/
  shesha-enterprise/             # Enterprise plugin (workflow, doc gen, ref numbers)
    .claude-plugin/plugin.json   # Plugin manifest (name, version)
    skills/                      # All skills live here
      {skill-name}/
        SKILL.md                 # Required - skill definition
        reference/               # Optional - supporting docs
        scripts/                 # Optional - executable code
        assets/                  # Optional - templates, boilerplate
  shesha-utils/                  # Utility plugin (analyzers, tests, setup, skill authoring)
    .claude-plugin/plugin.json
    skills/
      {skill-name}/
        SKILL.md
```

## Creating and Updating Skills

**MANDATORY**: When creating a new skill or updating an existing one, you MUST use one of these skill creator skills:

- **`/skill-creator`** — General-purpose skill authoring guide. Covers core principles (conciseness, progressive disclosure, degrees of freedom), SKILL.md structure, frontmatter conventions, bundled resource patterns, and a verification checklist. Use this for non-Shesha skills or when you need the foundational best practices.

- **`/shesha-skill-creator`** — Shesha-specific skill creator. Extends skill-creator with Shesha domain analysis (base classes, attributes, DI patterns, NHibernate requirements, folder conventions). Use this when the skill generates Shesha/.NET/ABP artifacts.

At minimum, read `plugins/shesha-utils/skills/skill-creator/SKILL.md` before authoring any skill to ensure compliance with:
- Frontmatter conventions (`name` + `description` only)
- Progressive disclosure (SKILL.md body under 500 lines)
- Reference file organization (one level deep, no extraneous docs)
- Verification checklist

## Key Conventions

- **Skill naming**: lowercase with hyphens (e.g., `domain-model`, `shesha-workflow`)
- **Skill folder name must match frontmatter `name`**
- **No extraneous files**: No README.md, CHANGELOG.md, or INSTALLATION_GUIDE.md inside skill folders
- **All entity properties must be `virtual`** (NHibernate requirement)
- **Forward slashes only** in file paths within skill docs (no Windows backslashes)
- **Plugin version**: Bump the `version` field in the affected plugin's `plugins/<plugin-name>/.claude-plugin/plugin.json` (e.g. `plugins/shesha-enterprise/.claude-plugin/plugin.json` or `plugins/shesha-utils/.claude-plugin/plugin.json`) **every time changes are pushed** to the remote. Do this as part of the commit being pushed. Version increment rules:
  - **Minor** (e.g., 1.6.0 → 1.7.0): When a **new skill** is added (new skill folder created).
  - **Patch** (e.g., 1.7.0 → 1.7.1): When **enhancements or fixes** are made to existing skills.

## Commit Message Style

Follow existing convention: `[type]- Description`

Types: `[feature]`, `[fix]`, `[chore]`

## Files to Never Commit

- `.claude/settings.local.json` — machine-specific local settings
