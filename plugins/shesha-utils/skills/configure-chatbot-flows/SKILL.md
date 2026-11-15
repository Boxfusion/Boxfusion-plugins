---
name: configure-chatbot-flows
description: Builds and configures a Shesha pd-chat chatbot (JSON bot flows) from given requirements, a flow diagram (Mermaid, draw.io, BPMN, image, PDF) or a design (Figma, screenshots, a spec document). Turns the input into a confirmed flow spec, designs the main and sub flows, writes the flow JSON using only the actions, forms and flows that exist, lints it, deploys it as drafts to a running host through the bot-flows API (or writes it into a module's seed flows), and tests it with scripted conversations through the bot tester. Use when the user wants to create, configure, set up, auto-configure or generate a chatbot, WhatsApp bot, bot menu or conversation flow from a description, requirements document, diagram, flowchart or design, or asks Claude to build the bot for them instead of using the designer by hand.
---

# Configure a chatbot from requirements, a diagram or a design

The bot is a set of **flows**: JSON documents the pd-chat engine runs (`message`, `prompt`, `choice`, `condition`,
`set`, `http`, `action`, `subflow`, `form`, `end` nodes). Flows are versioned `BotFlow` items in the database and are
edited in the portal's flow designer, which also has an **AI** button for small tweaks afterwards. This skill does the
whole build in one pass from a source of truth the user supplies.

Principles: the user confirms a written spec before anything is built; flows use only capabilities that really
exist on the target; everything is saved as **drafts** and tested before anything goes **Live**.

Rely on the scripts. Do not rewrite their logic inline:

- `scripts/extract_diagram.py <file>`: Mermaid, draw.io (also compressed) or BPMN to a node/edge summary.
- `scripts/flowtool.py lint | actions | deploy | chat`: offline lint, list host actions, draft/publish, scripted tests.
  Run it with `-h` for the options.

## Workflow

Copy this checklist and keep it current:

```
- [ ] 1. Intake: understand the source, extract a graph
- [ ] 2. Write the flow spec and get it confirmed
- [ ] 3. Discover the target (actions, forms, existing flows)
- [ ] 4. Design the flow set
- [ ] 5. Author the JSON
- [ ] 6. Lint and fix
- [ ] 7. Deploy as drafts
- [ ] 8. Test with scripted conversations
- [ ] 9. Report, and publish only when told to
```

### 1. Intake

Identify what was given and read it fully:

- **Text requirements / a document**: read it; note every journey, rule, number, wording and integration.
- **Diagram**: for Mermaid, draw.io, BPMN run `python scripts/extract_diagram.py <file> --json graph.json` and read the
  summary (shapes, branches, labels). For an image or PDF, view it directly and write the same node/edge list by hand.
- **Design (Figma, screens, wireframes, a prototype)**: treat each screen as a step and each button as an option.
  View exported images; if a Figma link was given and its connector is not authorised, say so and ask for exports.
- **Several of these**: they usually overlap; where they disagree, list the conflicts for the user instead of picking.

How shapes and phrases become nodes, and how to split a big diagram into flows:
[references/spec-and-diagram-mapping.md](references/spec-and-diagram-mapping.md).

### 2. Spec first

Write a compact spec (template in the reference) and show it to the user: the journeys, each step with its
prompt or message, inputs and validation, decisions, data calls, hand-offs, end states, wording you will use, and
**assumptions and open questions**. Ask only what blocks the build, in one batch: channels (WhatsApp, web chat, both),
entry behaviour, languages, which systems the bot calls (and their endpoints), when to hand to an agent, and the
target (step 3). Wait for confirmation; spec changes are cheap, rebuilt flows are not.

### 3. Discover the target

Ask which target applies:

- **A. A running host** (most common): get its URL and sign-in from the user. Never guess credentials; if sign-in is
  refused, stop and ask. Set the password in the `FLOWTOOL_PASSWORD` environment variable (never on the command
  line) and run `python scripts/flowtool.py actions --base-url <url> --user <user> --json actions.json`. Also read
  the existing flows (`GET api/bot-flows`) and WhatsApp forms (`GET api/whatsapp-forms`).
- **B. A project's source**: write the JSON into the module's `BotFlows/Seed/` and let the module's flow source ship
  it (see the `migrate-chatbot-to-flows` skill, step 5). List the actions by reading the `IFlowAction` classes and the
  chat module's `[FlowActionInfo]` attributes.

Use only the actions, forms and flows you can see. **Reuse before building**: a host usually already has `escalate`,
`endConversation`, rating and address flows; call them with `subflow` instead of redrawing them. Do not overwrite an
existing flow of the same name without telling the user.

### 4. Design the flow set

One entry flow (`main`: greeting, menu, routing) plus one flow per journey, with shared pieces (identify the
customer, capture an address, hand off to an agent, rating) as subflows. Name flows and nodes in camelCase after
what they do. Add `interrupts` on the entry flow for words that must work anywhere ("exit", "stop", "menu"). Keep
deployment values out of the JSON: `{{config.apiBaseUrl}}`, never a hardcoded host. Authoring rules and the node
reference: [references/authoring-guide.md](references/authoring-guide.md).

### 5. Author the JSON

Write one `<flowName>.json` per flow in a working folder (for example `flows/`; for target B the module's seed
folder). The file name is the flow name. Follow the authoring guide. Every `http` and `action` node gets an
`onError` path that tells the customer what happened and offers an agent; every flow ends; no dead ends.
If the spec needs a capability that does not exist (no action, no form, no API), do not fake it: leave the path
out or stub it with a clear message, list it under **Gaps** in your report, and offer to build the action (porting
pattern in the `migrate-chatbot-to-flows` skill's `references/porting-actions.md`).

### 6. Lint

```bash
python scripts/flowtool.py lint flows --actions actions.json
```

Fix every error. Read the warnings: over-long WhatsApp titles are cut on the channel, hardcoded hosts break other
environments. The host validates again on deploy and is the authority (it knows .NET regex syntax the offline lint
cannot check).

### 7. Deploy as drafts

```bash
python scripts/flowtool.py deploy flows --base-url <url> --user <user> --entry main --dry-run
python scripts/flowtool.py deploy flows --base-url <url> --user <user> --entry main
```

This validates on the host, then saves every flow as a **Draft** version, subflows first. Nothing goes Live and
running conversations are unaffected. Tell the user the drafts are in the designer
(`/dynamic/boxfusion.chat/bot-flows`) where they can open, tidy and edit them.

### 8. Test

Write a conversation script per journey and run it in draft mode (the host needs the chat setting **Bot Tester
Enabled**, normally off outside dev):

```bash
python scripts/flowtool.py chat tests/fault.json --base-url <url> --user <user> --mode draft
```

Cover each journey's happy path, one validation failure, each `condition` branch, an error path, "exit", and the
agent hand-off. Format and matrix: [references/testing-and-deploy.md](references/testing-and-deploy.md). The tester
runs real actions, so tell the user which side effects to expect (interactions, cases) and use a test user. Fix and
redeploy until the scripts pass. You may not claim a path works if it was not run.

### 9. Report, and publish only when told to

Report: the confirmed spec's coverage (each journey: built, tested, or not), assumptions made, **gaps** (what is
missing and what it needs), flows that already existed and were reused, and anything the tests could not cover.
Publishing replaces what new conversations get, so ask first. When the user agrees:

```bash
python scripts/flowtool.py deploy flows --base-url <url> --user <user> --entry main --publish --allow-update
```

`--allow-update` is only for flows that are already Live or for changing the entry flow, and only with the user's
explicit go-ahead. Rollback and version handling: the testing reference.

## Rules

- Never guess or reuse credentials from earlier work. Ask, and use the environment variable for the password.
- Never point a test at a real channel or message real customers. The bot tester only.
- Do not invent action keys, form names, flow names, endpoints or business rules. Ask or mark as a gap.
- Do not stage or commit unless asked.
- Customer-facing wording: use the user's own wording where they gave it; otherwise short, plain and consistent
  with the existing flows' tone. Say in the report which text is yours.
