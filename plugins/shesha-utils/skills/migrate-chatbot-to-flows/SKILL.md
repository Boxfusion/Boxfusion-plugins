---
name: migrate-chatbot-to-flows
description: Migrates a Shesha project's chatbot from the old Bot Framework Composer bot (adaptive .dialog files, custom DialogActions, BotConfiguration items, the Bot Composer admin component) to the pd-chat JSON flow engine (BotFlow items in the database, IFlowAction C# actions, the flow designer and bot tester). Inventories the Composer leftovers, upgrades the chat reference, ports dialogs to flows and custom actions to IFlowAction, ships the flows with the module, removes the Composer artefacts and verifies the result. Use when the user wants to upgrade, migrate, port or move a client project (eThekwini, Midvaal, RSL, AgriERP, any pd-chat consumer) from the old bot / Bot Composer / dialogs to bot flows, or asks why a project's Composer dialogs stopped working after taking a newer chat version.
---

# Migrate a chatbot from Bot Composer to bot flows

The pd-chat module no longer runs Composer dialogs. `FlowBot` replaces the Composer `IBot`; conversation logic is
**flows** (JSON, stored as `BotFlow` configuration items) and C# capabilities are **`IFlowAction`s**. The Bot
Framework channel adapters and middleware are unchanged. A project that took the new chat version keeps running
but with the chat module's default flows: its own Composer dialogs and `DialogAction`s are dead until ported.

The project's behaviour is the spec. The goal is the same conversations, expressed as flows, with tests that prove it.

## Prerequisites

- The project's Shesha is **0.43.38 or newer** (the chat module targets it). If lower, run the
  `upgrade-shesha-stack` skill first.
- The chat release that contains the flow engine. Do not guess a version: check the chat package's release notes or
  the feed for a version that contains the `BotFlow` type, or reference pd-chat locally (see step 2).
- Ask the user before anything destructive. This migration drops tables (step 6).

## Workflow

Copy this checklist and keep it current:

```
- [ ] 1. Inventory the Composer bot
- [ ] 2. Point the project at the flow-engine chat
- [ ] 3. Plan: map every dialog and custom action
- [ ] 4. Port custom actions to IFlowAction
- [ ] 5. Port dialogs to flows and ship them
- [ ] 6. Remove Composer, handle the data
- [ ] 7. Portal: designer, tester, menu
- [ ] 8. Verify
```

### 1. Inventory

Run `git status` first and report existing uncommitted changes so they can be told apart from this migration.
Then:

```bash
python scripts/scan_composer.py --repo <repo-root> --json composer-inventory.json
```

Read the report: dialogs (what each begins, triggers, recognisers), custom `$kind` values, custom action classes,
memory paths (`user.*`, `dialog.*`, `conversation.*`, `turn.*`), URLs, and the chat references in
`Directory.Build.props` / `package.json`. "No Composer leftovers" means there is nothing to port.

Also read the project's own bot customisations that are *not* in dialogs: settings, middleware, message
handlers, WhatsApp forms and anything that references the chat module's `DialogAction`/`Dialog` types.

### 2. Point the project at the new chat

- Backend: set `ChatVersion` in `backend/Directory.Build.props` to the flow-engine release. For local debugging
  against pd-chat use `UseLocalChat` (+ `ChatPath`); a project that has its **own dependents** (e.g. Dep) needs
  the same toggles there, because a dependent's NuGet reference to the old chat silently beats a local
  project reference.
- Frontend: bump `@shesha-io/chat-service` in `adminportal/package.json`.
- **Local toggles must go back to the released values before committing.**
- Build. Expect compile errors where code used removed types (`BotConfiguration`, `BotComposerSetting`,
  `DialogAction`, the Composer helpers). That list is your removal worklist (step 6), not a reason to restore them.

### 3. Plan

Write the mapping as a table before coding: each dialog → flow name(s); each custom action → one of
(a) an action the chat module **already ships** (keep the key, no port), (b) a new `IFlowAction`, (c) dropped.
List what the engine cannot express and how each is handled. Read
[references/dialog-to-flow-mapping.md](references/dialog-to-flow-mapping.md) for the construct mapping and
[references/porting-actions.md](references/porting-actions.md) for the shipped actions and the action template.

Confirm with the user the things that change behaviour: LUIS/QnA/FAQ (flows use regex `interrupts` and the
Copilot service, not LUIS), languages, channels in scope, and anything on the "not covered" list.

Do **not** invent a Composer→flow converter and run it blindly: adaptive-dialog memory scoping and trigger
semantics do not map mechanically. Port dialog by dialog, reading each one.

### 4. Port custom actions

One `IFlowAction` class per capability, key in camelCase, registered by convention (`ITransientDependency`). Copy the
original logic; change only the plumbing (inputs from `context.Params`, output through `FlowActionResult.Ok`, messages
through `Messages`). A failed lookup should **return a result** the flow can branch on, not throw: an exception
fails the node through `onError`. Add `[FlowActionInfo]` / `[FlowActionParam]` so the designer and the AI
configurator can describe it. Details and the template: [references/porting-actions.md](references/porting-actions.md).

### 5. Port dialogs to flows and ship them

- One JSON file per flow in `<Module>/BotFlows/Seed/<flowName>.json` (the file name is the flow name), with
  `<EmbeddedResource Include="BotFlows\Seed\*.json" />` in the csproj.
- A source class: `public class <Client>BotFlowSource : EmbeddedBotFlowSource, ITransientDependency` passing
  `typeof(<Client>BotFlowSource).Assembly`; override `EntryFlow` if the entry flow is not `main`.
- A flow with the same name as a chat default (`main`, `escalate`, ...) **replaces** that default on environments
  where the default is still exactly as shipped; otherwise it is added only when no flow of that name exists.
- **Seeding never overwrites an edited flow.** On an environment that already has the flow, publish the changed
  JSON as a new version (`POST api/bot-flows/draft`, then `POST api/bot-flows/versions/{id}/publish`, or import a
  package). Say this to the user: "I changed the seed" does not change a deployed bot.
- Deployment values come from settings, never JSON: `{{config.apiBaseUrl}}` (the `ApiBaseUrl` bot setting), not a
  hardcoded host.
- WhatsApp forms the old bot sent with code: implement `IWhatsAppFormSource` and use the `form` node
  (see the mapping reference).

### 6. Remove Composer and handle the data

Delete what the scan listed: `dialogs/`, `language-*/`, `knowledge-base/`, `schemas/`, `*.dialog`, `*.botproj`,
`*.lu`/`*.qna`/`*.lg`, custom `DialogAction`/`Dialog` classes and their `DeclarativeType` registrations, the Composer
settings file, `AddBotRuntimeConfiguration` calls, `Bot-Composer-admin`, and any admin-portal form using the Bot
Composer component. Keep `AddBotRuntime`: the adapters and middleware need its storage and state.

**Data warning, confirm before running the migrations:** the chat migration `M20261028100000` is one way. It
deletes the `bot-configuration` configuration items and drops `chat_BotConfiguration` and
`chat_BotComposerSettings`. The zipped Composer projects stored there cannot be recovered afterwards. Ask the user
whether the environments' Composer projects have been exported, and take a database backup before the first run
against a real database. If a project ships `.shaconfig` packages containing `bot-configuration` items (the scan
lists them), remove those items from the packages: fresh installs crash on them.

### 7. Portal

In `adminportal`, create the forms `bot-flows`, `bot-flow-designer` and `bot-tester` (module `boxfusion.chat`) from
the JSON in the pd-chat repo (`adminportal/packages/chat/forms/`), add `/dynamic/boxfusion.chat/bot-flows` to the
main menu, and turn on the chat setting **Bot Tester Enabled** for non-production environments only.
`npm install` needs the private feed login, so the user may have to refresh credentials.

### 8. Verify

Follow [references/verification.md](references/verification.md): a flow-set test (every flow valid, every subflow
and action resolves), per-flow behaviour tests, a real host run through the bot tester, and the API checks. Report
what was run and what was not. Never claim a conversation works because the flows validate: validation proves
shape, not behaviour.

## Rules

- Do not stage or commit unless asked. Never commit the local debug toggles.
- Port behaviour, not structure. Where the Composer dialog had a bug, tell the user before changing behaviour.
- Never point a test host at a real channel (a compiled-in Meta default can hold a live token) or message real
  customers; use the bot tester or fake servers.
- If the old bot had per-language assets (`language-*`, `.lg`), say so to the user and agree how each language's
  text is handled: flows carry the text you write in them, and the channel middleware (translation, exit, expiry)
  is unchanged but is not a replacement for the old language files.
