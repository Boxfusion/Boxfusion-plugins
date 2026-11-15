# Verifying a migrated bot

Contents: flow-set test, per-flow tests, running host, API checks, what a green result does and does not prove,
cleanup before committing.

## 1. Flow-set test (always)

Add to the project's domain test project (references the chat Domain and Application assemblies). It proves the
shipped set is coherent. Adapt names:

```csharp
public class <Client>BotFlowsTests
{
    private static readonly IReadOnlyDictionary<string, string> Flows = new <Client>BotFlowSource().GetFlows();

    private static readonly Lazy<HashSet<string>> ActionKeys = new(() =>
        new[] { typeof(<Client>BotFlowSource).Assembly, typeof(boxfusion.chat.Common.Services.BotFlows.DefaultBotFlows).Assembly }
            .SelectMany(a => a.GetTypes())
            .Where(t => typeof(IFlowAction).IsAssignableFrom(t) && t.IsClass && !t.IsAbstract)
            .Select(t => ((IFlowAction)RuntimeHelpers.GetUninitializedObject(t)).Key)   // keys are constants
            .ToHashSet(StringComparer.OrdinalIgnoreCase));

    [Fact] public void Ships_the_entry_flow() => Flows.Keys.ShouldContain("main");

    [Fact] public void Every_flow_is_valid()
    {
        var problems = Flows.SelectMany(f => FlowDefinitionValidator.Validate(FlowDefinition.Parse(f.Value))
                                             .Select(e => $"{f.Key}: {e}")).ToList();
        problems.ShouldBeEmpty(string.Join(Environment.NewLine, problems));
    }

    // plus: every subflow exists; every action key is registered; no flow is orphaned (nothing calls it and it is not
    // the entry flow); no flow hardcodes a host (search the JSON for "http" outside {{config.*}}).
}
```

## 2. Behaviour tests (per ported flow)

Drive the real engine with fake actions, so a flow's branching is proven without a database:

```csharp
var engine = new FlowEngine(provider, new IFlowAction[] { new FakeLookup() }, new FakeHttp());
var session = new FlowSession();
var first  = await engine.StartAsync(session, "main");
var second = await engine.ContinueAsync(session, "2", new Activity { Text = "2" });
second.Messages.Select(m => m.PlainText) ... ; session.Waiting ...; result.Completed ...
```

Implement `IFlowDefinitionProvider` over the shipped JSON (`ResolvedFlow { Definition = FlowDefinition.Parse(json) }`)
and `IFlowHttpClient` as a fake. Cover, per dialog: the happy path with the original prompts and replies, each
validation retry and `maxAttempts` exit, each `condition` branch, each `onError` path, and each interrupt
("exit"). Port the project's existing Composer dialog tests: the original assertions are the spec. When a test
is dropped because the construct no longer exists, say so in the summary.

For each ported action, a unit test with its service faked: output shape, the not-found path, the failure path.

## 3. Run the host

1. Build the solution and run the existing tests; report any that fail with their output.
2. Start the host against a **scratch copy** of the database (restore a backup to a new name; never the shared
   dev/test DB). Migration `M20261028100000` runs and is destructive: confirm it is the copy.
3. Set `BotTester__Enabled=true` (env var or the chat setting) for the run only.
4. Sign in to the host API (`POST api/TokenAuth/Authenticate`) with credentials the user gives you. Do not guess
   passwords; if a login is refused, stop and ask.
5. API checks (`Authorization: Bearer <token>`):
   - `GET api/bot-flows` lists every shipped flow, one entry flow;
   - `GET api/bot-flows/actions`: every action the flows call is `available`;
   - `POST api/bot-flows/validate` for each flow's definition returns no errors;
   - publish one changed flow (`POST api/bot-flows/draft` then `POST api/bot-flows/versions/{id}/publish`) if the
     environment already has the old seed.
6. Talk to the bot with `POST api/bot-tester/message` `{ "text": "...", "mode": "live" }` (and `GET
   api/bot-tester/state` to see flow, node and variables). Walk the main menu, one full happy path per
   top-level journey, a validation failure, "exit", and an action that fails. `POST api/bot-tester/reset` between runs.

The tester runs the real turn runner as the `WebChat` channel for the signed-in user, so actions have **real side
effects** (interactions, cases, agent hand-off). Use a test user, and not a database anyone depends on.

## 4. What is not proven

State these plainly in the summary instead of implying coverage:

- WhatsApp: the tester skips the channel middleware (translation, expiry, message shaping) and never talks to
  Meta. Forms published to Meta are not exercised. Do not send to real numbers.
- Actions that need a module the test host lacks (ServiceManagement's `IIncidentManagement`) fail through `onError`.
- The portal pages (designer, list, tester): `npm install` needs the private feed login. If it could not run, say
  the portal was not built or viewed.
- Anything that depends on production data volumes, real customers or real third-party APIs.

## 5. Before finishing

- Local debug toggles back to released values (`UseLocalChat`, `ChatPath`, `useLocalChat` in `next.config.js`, local
  `skipDbHealthChecks`, any scratch connection string).
- No `.dialog`/`.botproj` leftovers (re-run `scripts/scan_composer.py`; expect "No Composer leftovers found").
- Release-note entry covering: the one-way migration, client customisations re-authored as flows, behaviour changes
  you made, and what is not covered.
- Leave everything unstaged unless the user asked you to commit.
