---
name: skill-creator
description: Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations.
---

# Skill Creator

This skill provides guidance for creating effective skills.

## About Skills

Skills are modular, self-contained packages that extend Claude's capabilities by providing specialized knowledge, workflows, and tools. They transform Claude from a general-purpose agent into a specialized agent equipped with procedural knowledge that no model can fully possess.

### What Skills Provide

1. Specialized workflows - Multi-step procedures for specific domains
2. Tool integrations - Instructions for working with specific file formats or APIs
3. Domain expertise - Company-specific knowledge, schemas, business logic
4. Bundled resources - Scripts, references, and assets for complex and repetitive tasks

## Core Principles

### Concise is Key

The context window is a public good. Skills share the context window with everything else Claude needs: system prompt, conversation history, other Skills' metadata, and the actual user request.

**Default assumption: Claude is already very smart.** Only add context Claude doesn't already have. Challenge each piece of information: "Does Claude really need this explanation?" and "Does this paragraph justify its token cost?"

Prefer concise examples over verbose explanations.

### Set Appropriate Degrees of Freedom

Match the level of specificity to the task's fragility and variability:

**High freedom (text-based instructions)**: Use when multiple approaches are valid, decisions depend on context, or heuristics guide the approach.

**Medium freedom (pseudocode or scripts with parameters)**: Use when a preferred pattern exists, some variation is acceptable, or configuration affects behavior.

**Low freedom (specific scripts, few parameters)**: Use when operations are fragile and error-prone, consistency is critical, or a specific sequence must be followed.

Think of Claude as exploring a path: a narrow bridge with cliffs needs specific guardrails (low freedom), while an open field allows many routes (high freedom).

### Anatomy of a Skill

Every skill consists of a required SKILL.md file and optional bundled resources:

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter metadata (required)
│   │   ├── name: (required)
│   │   └── description: (required)
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/     - Executable code (Python/Bash/etc.)
    ├── references/  - Documentation loaded into context as needed
    └── assets/      - Files used in output (templates, icons, fonts, etc.)
```

#### SKILL.md (required)

- **Frontmatter** (YAML): Contains `name` and `description` fields (required). Only `name` and `description` are read by Claude to determine when the skill triggers.

- **Body** (Markdown): Instructions and guidance. Only loaded AFTER the skill triggers.

#### Bundled Resources (optional)

##### Scripts (`scripts/`)

Executable code for tasks requiring deterministic reliability or repeatedly rewritten.

- **When to include**: When the same code is being rewritten repeatedly or deterministic reliability is needed
- Scripts may be executed without loading into context — token efficient and deterministic

##### References (`references/`)

Documentation loaded as needed into context.

- **When to include**: For documentation Claude should reference while working
- Keeps SKILL.md lean, loaded only when Claude determines it's needed
- If files are large (>10k words), include grep search patterns in SKILL.md
- Avoid duplication: information should live in either SKILL.md or references, not both

##### Assets (`assets/`)

Files not intended to be loaded into context, but used within the output Claude produces.

- **When to include**: When the skill needs files used in final output (templates, images, boilerplate)

#### What NOT to Include

Do NOT create extraneous documentation files: README.md, INSTALLATION_GUIDE.md, QUICK_REFERENCE.md, CHANGELOG.md, etc. The skill should only contain information needed for an AI agent to do the job.

### Progressive Disclosure

Skills use a three-level loading system:

1. **Metadata (name + description)** - Always in context (~100 words)
2. **SKILL.md body** - When skill triggers (<5k words)
3. **Bundled resources** - As needed by Claude (unlimited)

Keep SKILL.md body under 500 lines. Split content into separate files when approaching this limit. Reference them from SKILL.md and describe clearly when to read them.

**Key principle:** When a skill supports multiple variations, keep only the core workflow and selection guidance in SKILL.md. Move variant-specific details into separate reference files.

**Pattern 1: High-level guide with references**

```markdown
# PDF Processing

## Quick start
[core example]

## Advanced features
- **Form filling**: See [FORMS.md](FORMS.md) for complete guide
- **API reference**: See [REFERENCE.md](REFERENCE.md) for all methods
```

**Pattern 2: Domain-specific organization**

```
bigquery-skill/
├── SKILL.md (overview and navigation)
└── reference/
    ├── finance.md
    ├── sales.md
    └── product.md
```

**Important guidelines:**
- Avoid deeply nested references — keep one level deep from SKILL.md
- For reference files longer than 100 lines, include a table of contents at the top

## Skill Creation Process

1. Understand the skill with concrete examples
2. Plan reusable skill contents (scripts, references, assets)
3. Create the skill directory and SKILL.md
4. Edit the skill (implement resources and write SKILL.md)
5. Verify the skill meets requirements
6. Iterate based on real usage

### Step 1: Understanding the Skill

Clearly understand concrete examples of how the skill will be used. Ask questions like:
- "What functionality should this skill support?"
- "Can you give examples of how this skill would be used?"
- "What would a user say that should trigger this skill?"

### Step 2: Planning Reusable Contents

Analyze each example by:
1. Considering how to execute on the example from scratch
2. Identifying what scripts, references, and assets would be helpful when executing repeatedly

### Step 3: Create the Skill

Create the skill directory under `.claude/skills/{skill-name}/` with SKILL.md.

### Step 4: Edit the Skill

Remember the skill is being created for another instance of Claude to use. Include information that would be beneficial and non-obvious to Claude.

For design patterns, consult:
- **Multi-step processes**: See [references/best-practices.md](references/best-practices.md) for workflow patterns
- **Output formats**: See [references/output-patterns.md](references/output-patterns.md) for template and example patterns

#### Frontmatter

Write YAML frontmatter with `name` and `description`:

- `name`: Skill name (max 64 chars, lowercase letters/numbers/hyphens, must match folder name)
- `description`: Primary triggering mechanism. Include both what the skill does AND when to use it. Write in third person. All "when to use" information goes here — NOT in the body.

Do not include any other fields in YAML frontmatter.

#### Body

Write instructions for using the skill and its bundled resources. Use imperative/infinitive form.

### Step 5: Verify

Check that:
- [ ] SKILL.md body is under 500 lines
- [ ] Frontmatter has only `name` and `description`
- [ ] `name` matches folder name
- [ ] Description is third person, includes what + when
- [ ] No time-sensitive information
- [ ] Consistent terminology throughout
- [ ] References are one level deep
- [ ] No Windows-style paths (use forward slashes)
- [ ] No extraneous documentation files

### Step 6: Iterate

1. Use the skill on real tasks
2. Observe struggles or inefficiencies
3. Update SKILL.md or bundled resources
4. Test again
