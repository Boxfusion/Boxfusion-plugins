# Workflow Patterns

## Sequential Workflows

For complex tasks, break operations into clear, sequential steps. Provide an overview of the process towards the beginning of SKILL.md:

```markdown
Filling a PDF form involves these steps:

1. Analyze the form (run analyze_form.py)
2. Create field mapping (edit fields.json)
3. Validate mapping (run validate_fields.py)
4. Fill the form (run fill_form.py)
5. Verify output (run verify_output.py)
```

## Conditional Workflows

For tasks with branching logic, guide Claude through decision points:

```markdown
1. Determine the modification type:
   **Creating new content?** → Follow "Creation workflow" below
   **Editing existing content?** → Follow "Editing workflow" below

2. Creation workflow: [steps]
3. Editing workflow: [steps]
```

## Feedback Loops

Common pattern: Run validator → fix errors → repeat. This greatly improves output quality.

```markdown
1. Make edits
2. Validate immediately
3. If validation fails:
   - Review error message
   - Fix the issues
   - Run validation again
4. Only proceed when validation passes
```

## Checklists for Complex Tasks

For particularly complex workflows, provide a checklist Claude can track:

```markdown
Copy this checklist and track progress:

Task Progress:
- [ ] Step 1: Analyze inputs
- [ ] Step 2: Create plan
- [ ] Step 3: Validate plan
- [ ] Step 4: Execute
- [ ] Step 5: Verify output
```
