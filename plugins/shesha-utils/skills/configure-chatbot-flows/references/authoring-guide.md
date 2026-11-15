# Authoring bot flows

Contents: file shape, node reference, channel limits, patterns, validation regexes, wording, what the validator
rejects.

## File shape

One `<flowName>.json` per flow; the file name is the flow name (letters, digits, `-`, `_`; not `draft`, `validate`,
`versions`, `actions`, `ai`).

```json
{
  "label": "Report a fault",
  "description": "Collects the fault type and address and logs a case.",
  "start": "askType",
  "interrupts": [ { "pattern": "^\\s*(exit|stop|menu)\\b", "next": "bye" } ],
  "nodes": { "askType": { "type": "choice", "...": "..." } }
}
```

`label` and `description` are optional metadata (flowtool lifts them out). `interrupts` belong on the entry flow
only; they jump out of whatever the customer was doing. Do not write a `layout` block: the designer lays nodes out.

## Node reference

| `type` | Fields | Notes |
| --- | --- | --- |
| `message` | `text`, `next` | Sends text, continues. |
| `prompt` | `text`, `var`, `next`; `validate` (regex), `invalidText`, `maxAttempts` + `onMaxAttempts`, `acceptAttachment`, `silent` | Asks and waits; the reply goes into `var`. `silent: true` with no `text` just waits (used after a form). |
| `choice` | `text`, `var`; `options` `[{ title, value, description, next }]` or `optionsFrom` (a variable holding a list of `{title, value}`); default `next`; `header`, `footer`, `buttonLabel`; `pageSize`, `nextLabel`, `backLabel`, `onBack`; `indexVar`, `titleVar`; `maxAttempts` + `onMaxAttempts` | Customer taps or types an option; `value` (or the title) lands in `var`. Every option needs its own `next` or the node needs a default `next`. |
| `condition` | `branches` `[{ when, next }]`, `else` | First matching branch wins; `else` is required. |
| `set` | `values` `{ name: value }`, `next` | A string starting `=` is an expression. Objects are allowed. |
| `http` | `method`, `url`, `body`, `saveAs`, `next`, `onError` | URL starts `{{config.apiBaseUrl}}`. |
| `action` | `action`, `params`, `saveAs`, `next`, `onError` | Key must exist on the host. Params can use `{{templates}}`. |
| `subflow` | `flow`, `next` | Runs the other flow to its `end`, then continues at `next`. The flow must be Live (or in the same deploy). |
| `form` | `form`, `text`, `buttonLabel`, `var`, `data`, `errorText`, `next`, `onError`, `maxAttempts` + `onMaxAttempts` | Sends a published WhatsApp form; answers land in `var`. The form must exist. |
| `end` | `all` | `true` ends the whole conversation; `false` returns to the caller. |

Templates: `{{var}}`, `{{var.field}}` in any text. Always available: `{{turn.channel}}`, `{{turn.fromId}}`,
`{{turn.conversationId}}`, `{{config.apiBaseUrl}}`, `{{lastError}}` (after a failed `http`/`action`).
Expressions (`when`, `=` values): `==`, `!=`, `<`, `+`, `null`, `true`, `false`, and `if`, `equals`, `count`, `join`,
`isEmpty`, `concat`. Variable lookups are case-insensitive. Write `status == "open"` or `result != null`.

## Channel limits (WhatsApp)

| Thing | Limit | What happens past it |
| --- | --- | --- |
| Options in a `choice` | up to 3 render as reply buttons; up to 10 as a list | use `pageSize: 10`; Next/Back rows count toward the page |
| Option `title` | 24 characters | cut |
| Option `description` | 72 characters | cut |
| `header` | 60 characters | cut |
| Choice body (`text`) | 1024 characters | cut; split long text into a `message` first |
| Plain `message` text | 4096 characters | cut |
| Form `buttonLabel` | 30 characters | validator error |

Web chat has no such limits, but write for the tightest channel the bot serves. The channel layer degrades
a menu to numbered text when interactive messages are off, so wording must work as "reply 1, 2 or 3" too.

## Patterns

**Ask, validate, retry, give up**

```json
"askPhone": { "type": "prompt", "text": "What is your cell number?", "var": "phone",
  "validate": "^(\\+27|27|0)[6-8][0-9]{8}$", "invalidText": "That number does not look right. Please try again.",
  "maxAttempts": 3, "onMaxAttempts": "phoneFailed", "next": "confirmPhone" }
```

**Confirm what you captured**

```json
"confirmPhone": { "type": "choice", "text": "Is {{phone}} correct?", "var": "phoneOk",
  "options": [ { "title": "Yes", "value": "yes", "next": "nextStep" }, { "title": "No", "value": "no", "next": "askPhone" } ] }
```

**Call a system and never leave the customer stranded**

```json
"lookup": { "type": "http", "method": "GET", "url": "{{config.apiBaseUrl}}/api/services/app/Case/Get?id={{caseNo}}",
  "saveAs": "caseInfo", "next": "found", "onError": "lookupFailed" },
"found":  { "type": "condition", "branches": [ { "when": "caseInfo != null", "next": "showCase" } ], "else": "notFound" },
"lookupFailed": { "type": "message", "text": "Sorry, I could not reach the system. Let me get you to an agent.", "next": "toAgent" },
"toAgent": { "type": "subflow", "flow": "escalate", "next": "done" }
```

**Menu from data** (an action fills a list, the choice shows it)

```json
"loadTypes": { "type": "action", "action": "getCaseTypes", "params": { "category": "{{category}}" }, "saveAs": "types", "next": "pickType", "onError": "toAgent" },
"pickType":  { "type": "choice", "text": "What is it about?", "var": "typeValue", "optionsFrom": "types", "pageSize": 10, "next": "afterType" }
```

**Entry flow skeleton**: optional `shouldWelcome` action, a greeting `message`, a `choice` menu whose options each
`subflow` into a journey, an `end` with `all: true`, and an `interrupts` entry so "exit" always works.

Rules of thumb:

- Every `http`, `action` and `form` node has an `onError`. Every retry loop is bounded with `maxAttempts`.
- Every journey is reachable from the menu and ends at an `end`. Agent hand-off is reachable from every path that can fail.
- One question per node. Do not stack a `message` and a `prompt` that say the same thing.
- Do not parse free text with regex to guess intent. Offer a `choice`.
- Variables are flat camelCase names; they live for the conversation only. Persist anything that must survive through an action.
- Never put hosts, keys or tenant values in the JSON. Anything environment-specific comes from `{{config.*}}`.

## Validation regexes (check each against the examples you were given)

| Input | Pattern |
| --- | --- |
| Email | `^[^@\s]+@[^@\s]+\.[^@\s]+$` |
| South African mobile | `^(\+27\|27\|0)[6-8][0-9]{8}$` |
| South African ID (13 digits) | `^\d{13}$` |
| Digits only, 6 | `^\d{6}$` |
| Non-empty text | `^\S.*$` |
| Name (letters, spaces, `'`, `-`) | `^[\p{L}][\p{L} '\-]{0,49}$` (.NET syntax; the host validates it) |

In JSON each backslash is doubled: `"^\\d{13}$"`. In a table cell above, `\|` is the Markdown escape for `|`; write `|` in JSON.

## Wording

Short, plain sentences. One idea per message. Tell the customer what to do next ("Reply with your 6 digit account
number."). Confirm what was captured. Apologise once, then offer a way forward. Use the user's own copy where
given. Bold is `**text**` in existing flows; check an existing flow on the host before using other formatting.

## What the validator rejects

Unknown node type; missing required field for the type; any `next`/`onError`/`else`/option `next` pointing at a
missing node; an option with no `next` and no node default `next`; `maxAttempts` without `onMaxAttempts`; `pageSize`
off a `choice`; a regex or expression that does not compile; a missing `start`; a node unreachable from `start` or an
interrupt (a quiet note while editing, an error on publish); a `subflow` with no Live version at publish time.
