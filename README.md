# Boxfusion Plugins

Welcome to the Boxfusion Plugins repository! This open-source project provides a collection of custom commands and plugins for Shesha, designed to extend functionality and streamline your development workflow.

## Overview

Boxfusion Plugins is an extensible skills framework that allows developers to create and share custom skills for Claude. Skills are documentation-based guides that help automate tasks, standardize processes, and share best practices across your team. Whether you're setting up .NET analyzers, configuring authentication, or establishing coding standards, this repository provides a simple way to package and distribute your knowledge.

## Getting Started

### Prerequisites

Before you begin, ensure you have:

- Claude CLI installed
- Git installed on your machine
- Basic understanding of Markdown (for creating skill documentation)

## Installation

### Via Claude Plugin Marketplace

The easiest way to install Boxfusion Plugins is through the Claude plugin marketplace:

1. **Add the plugin to the marketplace**

   ```bash
   /plugin marketplace add ./
   ```

2. **Open the marketplace**
   - Run: /plugin enter

   - Use the arrow keys to navigate to the Marketplace tab

3. **Navigate to Boxfusion Plugins**
   - Scroll down or search for "Boxfusion Plugins"

4. **Browse available plugins**
   - Click "Browse Plugins" to see all available commands

5. **Install for your team**
   - Click "Install for all collaborators" to make plugins available to your entire team

## Creating Custom Skills

Skills allow you to extend Shesha's functionality with custom commands and workflows. Here's how to create your own:

### Skill Structure

Each skill is a folder containing a `SKILL.md` file with metadata and instructions:

```
skills/
└── your-skill-name/
    └── SKILL.md
```

### Step-by-Step Guide

1. **Navigate to the skills directory**

   ```bash
   cd skills
   ```

2. **Create a new folder for your skill**

   ```bash
   mkdir your-skill-name
   ```

   **Naming conventions:**
   - Use lowercase with hyphens (e.g., `add-analyzers`, `setup-authentication`)
   - Make it descriptive and specific
   - Avoid generic names

3. **Create the SKILL.md file**

   ```bash
   cd your-skill-name
   touch SKILL.md
   ```

4. **Add frontmatter and content**

   Every `SKILL.md` file must start with YAML frontmatter containing the skill metadata:

   ```markdown
   ---
   name: your-skill-name
   description: Brief description of what this skill does and when to use it
   ---

   # Your Skill Title

   Detailed documentation of your skill...
   ```

### Skill Template

Here's a complete template for creating a new skill:

```markdown
---
name: your-skill-name
description: Use this skill to [describe the main purpose and when to trigger this skill]
---

# Skill Title

Brief overview of what this skill accomplishes.

## Overview

Explain what the skill does and what problems it solves.

## Step 1: [First Step Title]

Detailed instructions for the first step.

# Example commands

command-example

## Step 2: [Second Step Title]

Continue with additional steps as needed.

### Important Notes

- Any special considerations
- Prerequisites or requirements
- Common pitfalls to avoid

## Example Usage

Provide concrete examples of how to use this skill.

---
```

### Best Practices

- **Clear naming**: Use descriptive frontmatter names and descriptions
- **Be specific**: Clearly define when and how to use the skill
- **Step-by-step**: Break down complex tasks into numbered steps
- **Include examples**: Show real code snippets and commands
- **Document prerequisites**: List any required tools or setup
- **Use code blocks**: Format commands and code properly with syntax highlighting

## Running the Project

### Using Skills in Claude

Once installed via the marketplace, skills are automatically available in Claude:

1. **Trigger skills naturally** - Claude will automatically use relevant skills based on your requests
2. **Browse available skills** - Use the marketplace to see all installed skills
3. **Share with team** - Skills installed for all collaborators are immediately available

### Local Development

If you're developing skills locally:

```bash
# Navigate to the project
cd boxfusion-plugins

# Add to Claude's plugin marketplace
/plugin marketplace add ./

# Your skills are now available in Claude
```

## Contributing

We welcome contributions from the community! Here's how you can help:

### How to Contribute

1. **Fork the repository**

   ```bash
   git clone https://github.com/Boxfusion/Boxfusion-plugins.git
   ```

2. **Create a feature branch**

   ```bash
   git checkout -b feature/new-skill-name
   ```

3. **Create your skill**

   ```bash
   cd skills
   mkdir your-new-skill
   cd your-new-skill
   touch SKILL.md
   ```

4. **Commit your changes**

   ```bash
   git add .
   git commit -m "Add [skill-name] skill for [purpose]"
   ```

5. **Push to your fork**

   ```bash
   git push origin feature/new-skill-name
   ```

6. **Open a Pull Request**
   - Describe what your skill does and when to use it
   - Include examples of the skill in action
   - Reference any related issues

### Contribution Guidelines

- Follow the skill template structure
- Use clear, descriptive frontmatter
- Include step-by-step instructions
- Provide code examples where applicable
- Test your skill before submitting
- Update documentation as needed
- Be respectful and collaborative

## Project Structure

```
├── .claude/
│   ├── settings.json
│   └── settings.local.json
├── .claude-plugin/
│   └── marketplace.json
└── plugins/
    ├── shesha-enterprise/
    │   ├── .claude-plugin/
    │   │   └── plugin.json
    │   └── skills/
    │       ├── analyze-workflow-state/
    │       ├── shesha-document-generation/
    │       ├── shesha-ref-numbers/
    │       └── shesha-workflow/
    └── shesha-utils/
        ├── .claude-plugin/
        │   └── plugin.json
        └── skills/
            ├── add-analyzers/
            ├── clean-form-config/
            ├── create-integration-tests/
            ├── document-shaconfigs/
            ├── harden-permissions/
            ├── link-backend-module-debug/
            ├── run-integration-tests/
            ├── shesha-project-setup/
            ├── shesha-skill-creator/
            ├── skill-creator/
            └── upgrade-shesha-stack/
```

## Troubleshooting

### Common Issues

**Plugin not showing in marketplace**

- Ensure you've run `/plugin marketplace add ./` from the project root directory
- Verify you're in the correct directory (should contain the `skills` folder)
- Refresh the marketplace view

**Skill not being triggered**

- Check that your `SKILL.md` frontmatter is properly formatted with `name` and `description`
- Ensure the description clearly indicates when the skill should be used
- Verify the skill is installed for all collaborators

**SKILL.md not recognized**

- Verify the file is named exactly `SKILL.md` (case-sensitive)
- Check that YAML frontmatter is properly formatted with `---` delimiters
- Ensure the skill folder is directly under the `skills` directory

---

**Made with ❤️ by the Boxfusion community**

For questions or support, please open an issue or reach out to our community channels.
