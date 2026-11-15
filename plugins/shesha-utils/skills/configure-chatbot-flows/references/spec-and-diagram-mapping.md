# From requirements, diagrams and designs to a flow spec

Contents: the spec template, diagram shapes to nodes, requirement phrases to nodes, splitting into flows,
reading a design, ambiguity checklist.

## Spec template

Show this to the user for confirmation before authoring. Keep it short; tables beat prose.

```markdown
# <Bot name>: flow spec
Channels: WhatsApp / web chat | Entry: <what happens on first message> | Languages: <...>
Hand-off to agent when: <rules> | Systems called: <API / action, purpose>

## Journeys
### 1. <Report a fault>   (flow: reportFault)
| # | Step | Customer sees | Input / validation | Next |
|---|------|---------------|--------------------|------|
| 1 | askType | "What is the problem?" + options Water / Electricity | choice | 2 |
| 2 | askAddress | "Where is it?" | free text, 3 tries | 3, else agent |
| 3 | log | (calls logIncident) | - | success msg / error -> agent |
End states: case logged (ref shown), abandoned after 3 tries, handed to agent.

## Shared pieces reused:  escalate, endConversation, serviceRating ...
## Words that work anywhere:  exit | stop -> endConversation
## Assumptions:  ...
## Open questions:  ...
## Gaps (needs something that does not exist yet):  ...
```

## Diagram shapes to nodes

| Diagram element | Usually becomes |
| --- | --- |
| Start / terminator | the flow's `start` (the first real node, no node for "Start" itself) |
| End / terminator | `end` (`all: true` for "conversation over", `all: false` when it returns to a caller flow) |
| Process box with customer-facing text | `message` |
| Parallelogram / "ask", "enter", "provide" | `prompt` (free text) |
| Decision whose branches are options the customer picks ("Report fault / Billing / Agent") | `choice` with one option per branch |
| Decision on data or a rule ("Address found?", "Is member?") | `condition` with a `when` expression; `else` is the other branch |
| Box that calls a system ("Log case", "Look up balance", "Check agent online") | `action` if one exists, else `http`; both with `onError` |
| Subprocess / predefined process / "see flow X" | `subflow` |
| Document / form shape, or text like "form", "WhatsApp form" | `form` (the form must exist or be listed as a gap) |
| Arrow back to an earlier box | `next` pointing at that node (retry loop); bound loops with `maxAttempts` |
| Label on an arrow out of a decision | the option `title` (choice) or the `when` condition |
| Swimlane "Agent" / "Human" | hand-off through the `escalate` flow or action |

Decide a decision's type by asking *who decides*: the customer (choice) or the system (condition). When the diagram
does not say, default to the customer deciding if the arrow labels read like menu items, and ask if unclear.

## Requirement phrases to nodes

| Requirement says | Build |
| --- | --- |
| "Greet the customer", "tell them..." | `message` |
| "Ask for their <x>" | `prompt` with `var` and validation; say what "valid" means |
| "Let them choose..." | `choice`; more than 10 items -> `pageSize: 10` |
| "If <x> then..." | `condition` |
| "Look up / fetch / check <x>" | `action` or `http` |
| "Give up after N tries" | `maxAttempts` + `onMaxAttempts` |
| "At any time they can say stop" | `interrupts` on the entry flow |
| "Then hand over to an agent" | `subflow` `escalate` (or the host's equivalent) |
| "Rate the service" | the host's rating flow, as a subflow |
| "Send a form" | `form` node |
| "Remember <x> for later in the chat" | a variable (`var` / `set`); it lives for the conversation only |
| "Remember <x> for next time" | needs the database: an action. Flag it as a gap if none exists |

## Splitting a diagram into flows

- The top-level menu and routing are the entry flow `main`. Each menu branch that has more than about 6 steps, or
  that more than one place uses, becomes its own flow called by a `subflow` node.
- A sub-diagram on a separate page or drawn as a subprocess box is a flow.
- A flow should fit on one screen of the designer (about 15 nodes). Split before that.
- A path that repeats in two journeys (collect address, confirm phone number, rating) becomes one shared flow.
- Subflows return to their caller at `end` with `all: false`; `all: true` ends the whole conversation.

## Reading a design (screens, wireframes, Figma)

A chat design shows what the customer sees, not the logic. Extract: each distinct message or screen as a node; each
button or list row as a `choice` option; each input field as a `prompt`; each error state as the `invalidText` or an
`onError` path; each "loading" or lookup as an `action`/`http`. Record the exact copy from the design in the spec:
it is the customer-facing wording. Note anything the design does not specify (what happens on error, on timeout, on
"back") as an assumption or open question: designs almost always omit the unhappy paths, and the bot needs them.

## Ambiguity checklist

Resolve or record, before building:

- What starts a conversation, and what do returning customers see?
- What happens on invalid input, no answer, "back", "menu", "exit"?
- Is the customer identified (profile lookup, phone number)? From what?
- Which steps call a system, with which endpoint, and what if it is down?
- When and how does a person take over, and what if no agent is online?
- Languages, tone, and any legally required wording (consent, privacy).
- Channel differences: does web chat need something WhatsApp cannot show (and vice versa)?
- What counts as done: a case reference, a confirmation, a rating?
