# Composer dialog constructs to flow nodes

Contents: flow format in brief, construct mapping, memory and templates, triggers and intents, things with no
direct equivalent, WhatsApp forms, a worked example.

## Flow format in brief

```json
{
  "start": "ask",
  "interrupts": [ { "pattern": "^\\s*(exit|thanks)\\b", "next": "bye" } ],
  "nodes": {
    "ask":  { "type": "prompt",  "text": "What is your name?", "var": "name", "next": "hi" },
    "hi":   { "type": "message", "text": "Hello {{name}}!", "next": "done" },
    "bye":  { "type": "message", "text": "Goodbye.", "next": "done" },
    "done": { "type": "end", "all": true }
  }
}
```

| `type` | Fields (besides `next`) |
| --- | --- |
| `message` | `text` |
| `prompt` | `text`, `var`; `validate` (regex), `invalidText`, `maxAttempts` + `onMaxAttempts`, `acceptAttachment`, `silent` |
| `choice` | `text`, `var`; `options` `[{ title, value, description, next }]` or `optionsFrom` (a variable); `pageSize`, `nextLabel`, `backLabel`, `onBack`, `indexVar`, `titleVar`, `maxAttempts` + `onMaxAttempts`; default `next` for options without their own |
| `condition` | `branches` `[{ when, next }]`, `else` (required) |
| `set` | `values` (a string starting `=` is an expression) |
| `http` | `method`, `url`, `body`, `saveAs`, `onError` |
| `action` | `action` (key), `params`, `saveAs`, `onError` |
| `subflow` | `flow` |
| `form` | `form`, `text`, `buttonLabel` (30 chars max), `var`, `data`, `errorText`, `onError`, `onMaxAttempts` |
| `end` | `all`: `true` ends the whole conversation, `false` returns from the subflow |

Rules the validator enforces: known node types, required fields, every `next`/`onError`/`else`/option target
exists, regexes and expressions compile, every node is reachable from `start` or an interrupt, `maxAttempts`
needs `onMaxAttempts`, every `choice` option needs its own `next` or the node needs a default `next`.

Templates: `{{variable.path}}` in any text (objects render as compact JSON). Always available:
`{{turn.channel}}`, `{{turn.fromId}}`, `{{turn.conversationId}}`, `{{config.*}}` (`{{config.apiBaseUrl}}`),
`{{lastError}}`. Expressions (`when`, `=` values): `==`, `!=`, `<`, `+`, `null`/`true`/`false`, functions `if`,
`equals`, `count`, `join`, `isEmpty`, `concat`; lookups are case-insensitive.

## Construct mapping

| Composer | Flow |
| --- | --- |
| `Microsoft.SendActivity` | `message` (the `${...}` template becomes `{{...}}`) |
| `Microsoft.TextInput` | `prompt` (`property` becomes `var`; `validations`/`invalidPrompt` become `validate`/`invalidText`; `maxTurnCount` becomes `maxAttempts` + `onMaxAttempts`) |
| `Microsoft.NumberInput` | `prompt` with a numeric `validate` regex; the value is text, so compare or convert in an expression |
| `Microsoft.ConfirmInput` | `choice` with Yes/No options |
| `Microsoft.ChoiceInput` | `choice` (static `options`, or `optionsFrom` a variable an action filled) |
| `Microsoft.AttachmentInput` | `prompt` with `acceptAttachment: true` |
| `Microsoft.SetProperty` / `SetProperties` | `set` |
| `Microsoft.IfCondition` | `condition` with one branch, `else` for the false path |
| `Microsoft.SwitchCondition` | `condition` with one branch per case, `else` for default |
| `Microsoft.HttpRequest` | `http` (`resultProperty` becomes `saveAs`; failures go to `onError`) |
| custom `$kind` action | `action` node calling the ported `IFlowAction` |
| `Microsoft.BeginDialog` | `subflow` |
| `Microsoft.EndDialog` | `end` with `all: false` |
| `Microsoft.CancelAllDialogs` / `EndConversation` | `end` with `all: true` |
| `Microsoft.ReplaceDialog` | `subflow` followed by `end` `all: false`, or `next` into the other flow's first node if it is a node of this flow |
| `Microsoft.RepeatDialog` / `GotoAction` | `next` pointing back at the node (a cycle is allowed; one turn is capped at `MaxStepsPerTurn` nodes, so a cycle that never waits for the customer fails loudly) |
| `Microsoft.DeleteProperty` / `DeleteProperties` | `set` the variable to `"=null"` (confirm with the tester that later `isEmpty`/`!= null` checks behave) |
| `Microsoft.Foreach`, `ForeachPage`, `EditArray`, `BreakLoop`, `ContinueLoop` | no loop node: see below |
| `Microsoft.EndTurn`, `LogAction`, `TraceActivity`, `EmitEvent` | drop |

## Memory and templates

Composer scopes `user.*`, `conversation.*`, `dialog.*`, `turn.*`, `this.*` collapse to one set of flat
**conversation variables**. Choose names that do not collide (`dialog.address` and `user.address` cannot both be
`address`). Variables live in the conversation's session (`BotFlowConversation`) and are cleared when the
conversation ends: anything that must outlive a conversation (a known customer, a saved preference) belongs in the
database, read and written through an action, not in a variable.

`user.base_url` and any hardcoded host become `{{config.apiBaseUrl}}`. Settings-backed values the project needs in
flows beyond that: provide an `IFlowConfigProvider` that adds them to `config`.

Adaptive expressions (`equals(a,b)`, `exists(x)`, `string(x)`, `length(x)`) map to the engine's small set; rewrite
the condition rather than translating function by function, and let `POST api/bot-flows/validate` check it.

## Triggers, intents and recognisers

- `OnBeginDialog` is the flow's `start` node.
- Welcome / `OnConversationUpdateActivity`: the entry flow's first node. The chat `shouldWelcome` action tells a
  first message from a returning one.
- `RegexRecognizer` `OnIntent` that should work **anywhere** ("exit", "stop", "thanks", "menu"): a root-flow
  `interrupts` entry (case-insensitive regex, jumps out of every subflow). Intents that only matter in one
  dialog become that flow's own `choice`/`condition`.
- `LuisRecognizer`, `QnAMakerRecognizer`, `CrossTrainedRecognizerSet`: **not supported**. Free-text understanding
  is not a flow feature. Menu-driven paths become `choice` nodes; FAQ moves to the Copilot service (the chat
  module's `faq` flow is a placeholder). Tell the user what customers lose before removing it.
- `OnUnknownIntent` becomes the `else` of the relevant `condition`, or a `choice`'s `maxAttempts`/`onMaxAttempts`.

## No direct equivalent

- **Loops over arrays** (`Foreach`, `EditArray`): do the iteration in C# inside an action and return the result
  (for example a list of `{title, value}` for a `choice` `optionsFrom`, or a prebuilt message), or use an index
  variable with a `condition` and `set` that adds 1 (`"=index + 1"`), cycling back. Prefer the action: it is
  testable.
- **Choice paging**: set `pageSize` (10 fits one WhatsApp list). Next/Back rows count toward the page.
- **Rich cards, carousels and custom activities**: only text, header/footer, options and forms are modelled. A
  custom attachment is returned by an action in `FlowActionResult.Attachments`.
- **Dialog-level `OnError`**: use `onError` on `http`, `action` and `form` nodes.
- Anything on the chat module's known-gaps list at the version you are on (read `docs/backend/bot-flows.md` in
  pd-chat, and `GET api/bot-flows/actions` on a running host, which is the source of truth for available actions).

## WhatsApp forms

A form sent from code becomes data plus a `form` node. Implement
`IWhatsAppFormSource.GetFormsAsync()` (a `ITransientDependency` class) returning `WhatsAppFormSeed` items (`Name`,
`FlowJson`, and `PublishedMetaFlowId` + `Revision` when the form is already published on Meta from that exact
JSON, so it is live without a republish). Then in the flow:

```json
"sendForm": { "type": "form", "form": "elecFault", "text": "Tap below to log the fault.",
              "buttonLabel": "Open form", "var": "formAnswers", "data": { "accountNumber": "{{account}}" },
              "next": "afterForm", "onError": "formFailed", "maxAttempts": 2, "onMaxAttempts": "formAbandoned" }
```

Seeded forms are JSON-mode (the visual builder cannot express hand-written forms). Publishing always creates a new
Meta flow named `{Name} r{n}`; a published Meta flow cannot be replaced. Never publish from a test host.

## Worked example

Composer: a `TextInput` "What is your cell number?" validated by a regex, then `IfCondition` on
`dialog.cell == ''`, then `BeginDialog` `AddressHandlerDialog`.

```json
{
  "start": "askCell",
  "nodes": {
    "askCell": { "type": "prompt", "text": "What is your cell number?", "var": "cell",
                 "validate": "^\\+?\\d{9,13}$", "invalidText": "That number does not look right. Try again.",
                 "maxAttempts": 3, "onMaxAttempts": "giveUp", "next": "address" },
    "address": { "type": "subflow", "flow": "address", "next": "done" },
    "giveUp":  { "type": "message", "text": "Sorry, I could not get your number.", "next": "done" },
    "done":    { "type": "end", "all": false }
  }
}
```

The `IfCondition` disappeared: the validated prompt cannot return empty. Check each such simplification against the
original and keep a note of it for the user.
