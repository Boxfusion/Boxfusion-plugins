# Testing, deploying and rolling back

Contents: credentials, drafts vs Live, conversation scripts, the test matrix, safe-run rules, rollback, forms.

## Credentials and the host

- `--base-url` is the backend (for example `http://localhost:21021`), not the portal.
- Sign-in: `--user <name>` with the password in `FLOWTOOL_PASSWORD`, or a bearer token in `FLOWTOOL_TOKEN` /
  `--token`. Ask the user for them. If sign-in fails, stop: do not try other passwords.
- The authoring API (`api/bot-flows`) needs a signed-in user. The bot tester API needs the chat setting
  **Bot Tester Enabled** (`boxfusion.chat.BotTesterEnabled`); without it the endpoints return 404. Ask the user to turn
  it on for the test and off after, and keep it off in production.

## Drafts, Live and versions

- `deploy` saves each flow as a **Draft** version. If the newest version is already an open draft it is updated in
  place; if the newest is Live, a new Draft version is started. Live flows and running conversations are untouched.
- `deploy --publish` validates again, makes each draft **Live** (subflows first, since a subflow must be Live before
  its caller can be published) and retires the previous Live version. Conversations already running stay on the
  version they started on; new ones get the new one. Publishing an entry flow clears the entry flag on the others.
- Publishing over a Live flow or changing the entry flow needs `--allow-update`, which you only add after the user
  agrees. Never use it to get past the guard on your own.
- Two flows that call each other in a cycle cannot both be published in one pass (each needs the other Live); the tool
  warns. Break the cycle, or publish one of them through the designer.

## Rollback

Versions are never deleted by publishing. To go back: read the older version's JSON (`GET api/bot-flows/<name>?versionId=<id>`
or open it from the designer's version picker), save it as a new draft (`POST api/bot-flows/draft`) and publish that.
A discarded draft (`DELETE api/bot-flows/versions/<id>`) is only for versions that were never published.

## Conversation scripts

A script is a JSON array run in order through the tester (`flowtool.py chat script.json --base-url ... --mode draft`).
Each step:

```json
[
  { "say": "hi", "expect": ["Welcome", "How can I help"] },
  { "say": "option:Report a fault", "expect": ["What is the problem"] },
  { "say": "my tap leaks", "expectNot": ["error", "Sorry"], "expectNode": "askAddress" },
  { "reset": true }
]
```

- `say` is what the customer types. `option:<title>` taps the option with that title from the previous reply (matching
  is case-insensitive) and fails the step if there is no such option.
- `expect` / `expectNot` are case-insensitive substrings of everything the bot said in that reply (headers, text,
  footers, option titles). `expectNode` checks the node the conversation is waiting at.
- The first message starts the entry flow (in `draft` mode, each flow's newest Draft, else its Live version).
- A step fails on any engine error too. The script exits non-zero when any step fails.

## Test matrix

For each journey in the confirmed spec, a script covering:

1. Happy path from the first message to the end state, asserting the key texts.
2. One invalid input and the retry text; then `maxAttempts` exhausted and the exit path.
3. Every `condition` branch (set up the data so each branch fires, or accept which are reachable and say so).
4. A system failure: where you can cause one (an unavailable action on a host without the module), check the `onError`
   path; where you cannot, list it as not tested.
5. "exit" mid-journey, to check the interrupt.
6. The agent hand-off, if the journey has one.

Keep the scripts next to the flows (`tests/`) so the user can rerun them.

## Safe-run rules

- The tester runs the real turn runner as the web-chat channel for the signed-in user, so actions have **real side
  effects**: interactions, cases, agent hand-off. Use a test user and an environment whose data does not matter, and
  tell the user what was created.
- Never point a test host at a real WhatsApp number. The tester never talks to Meta.
- It skips the channel middleware (translation, expiry handling, message shaping) and WhatsApp rendering, so button and
  list layout and the character limits are covered by lint, not by the tester.

## WhatsApp forms

Forms are created and published in the portal's WhatsApp forms builder (`api/whatsapp-forms`). **Publishing a form
creates a new Flow on Meta and cannot be undone**: this skill never publishes forms. If the spec needs a form that does
not exist, build the flow so it can use it (`form` node pointing at the planned name), say the form is a gap, and let
the user create and publish it. The validator only checks that a form name is set; deploying a flow that names a
missing form fails at runtime with the node's `onError`.

## Afterwards

- The user refines drafts in the designer (**Tidy** lays the canvas out) and can use the **AI** button there for
  small changes to the open flow, or the **AI builder** button on the flow list to add or change whole flows from a
  description (both need the Flow AI Configurator API key set; the builder saves drafts only, after a review).
- A flow set built for a project's own source (target B) is covered by that project's flow-set test; see the
  `migrate-chatbot-to-flows` skill, `references/verification.md`.
