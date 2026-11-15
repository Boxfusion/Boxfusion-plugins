# Porting custom DialogActions to IFlowAction

Contents: the action contract, a template, conventions and pitfalls, actions the chat module already ships,
what to do about actions that were never ported.

## Contract

```csharp
public interface IFlowAction
{
    string Key { get; }
    Task<FlowActionResult> ExecuteAsync(FlowActionContext context, CancellationToken ct);
}
```

- `context.Params`: the node's `params`, with `{{templates}}` already rendered (a `JObject`).
- `context.Variables`: the conversation's variables; read them, but write through the result.
- `context.Activity`: the inbound Bot Framework activity (channel, sender, `Conversation.Id`, attachments).
- `FlowActionResult.Ok(token)`: `token` lands in the node's `saveAs` variable. `FlowActionResult.Fail(error)`: the node
  leaves through `onError` and `{{lastError}}` holds the text. `Messages` (list of `BotMessage`) and `Attachments`
  are sent to the customer.

## Template

Namespaces: `boxfusion.chat.Domain.Domain.BotFlows.Engine` (contract and attributes), `Abp.Dependency`.

```csharp
[FlowActionInfo("The status message of an electricity connection application.",
    Category = "<Client> incidents", Returns = "string, or null when not found")]
[FlowActionParam("eNumber", "The application reference number", Required = true, Example = "{{app.referenceNumber}}")]
public class ApplicationStatusFlowAction : IFlowAction, ITransientDependency
{
    private readonly IStatusService _status;
    public ApplicationStatusFlowAction(IStatusService status) => _status = status;

    public ILogger Logger { get; set; } = NullLogger.Instance;   // Castle.Core.Logging, property-injected

    public string Key => "applicationStatus";

    public async Task<FlowActionResult> ExecuteAsync(FlowActionContext context, CancellationToken ct)
    {
        var eNumber = (string?)context.Params["eNumber"] ?? string.Empty;
        try
        {
            return FlowActionResult.Ok(await _status.GetAsync(eNumber));
        }
        catch (Exception ex)
        {
            Logger.Warn("Status lookup failed.", ex);
            return FlowActionResult.Ok(null);   // the flow shows its "not found" text; do not fail the turn
        }
    }
}
```

Several small related actions can live in one file (`CustomerFlowActions.cs`).

## Conventions and pitfalls

- **Registration is by convention**: implement `ITransientDependency` on the class. Nothing else to register.
- **Key**: camelCase and equal to the class name minus `FlowAction`, camel-cased. The key of an action whose
  dependencies are missing can only be derived from the class name, so a different key makes it unreachable there.
  Keys must be unique across the host *and* the chat module; reusing a chat key replaces behaviour silently, so only do
  it deliberately and pin it with a test.
- **Optional dependencies**: an action whose dependency is not installed in a host is listed as unavailable and
  fails through `onError` instead of stopping the bot. Do not guard it by hand.
- **Failure semantics**: the Composer actions often ended the dialog on error. Decide per case. A lookup that may
  legitimately find nothing returns `Ok(null)` and the flow branches on `!= null`; a real failure returns `Fail(..)`
  and the node has an `onError` that apologises or escalates. A thrown exception is caught by the engine too, but then
  the log line is the only trace.
- **Inputs**: Composer actions read `dialog.*` memory directly. Make each input an explicit param, with an `Example`,
  so the designer and the AI configurator can wire it.
- **Output**: return one JSON object (`JObject.FromObject(...)`) rather than writing many variables; the flow reads
  `{{result.field}}`.
- **Scoped services**: the host resolves the action, runs it and releases it per node, so injecting scoped services
  is fine; never cache state in fields.
- **Castle property injection**: public settable properties on a *resolved* class are injected. A public array or
  collection setter gets an empty array. Mark such properties `[DoNotWire]`.
- **Tenant/user context**: the action runs inside the bot turn, not an authenticated portal request. Do not rely
  on `AbpSession.UserId`; derive the person from `context.Activity` (`From.Id`) or the variables.
- Keep database access in the same units of work the old action used; the conversation row is saved by the host.

## Actions the chat module already ships (do not re-port)

| Key | Purpose |
| --- | --- |
| `shouldWelcome` | First message, or already welcomed inside the expiry window |
| `getWebUserProfile`, `getUserInfo`, `getContactNumber`, `saveUser` | Resolve and save the customer (`Person`) |
| `resolveAddress` | Geocode a free-text address |
| `getMenuItems`, `getCaseTypes`, `refListItemName` | Menu options, case types, reference-list names |
| `buildFilter` | URL-encoded JsonLogic filter for the dynamic CRUD endpoints (customer input cannot alter it) |
| `checkStandalone` | Whether ServiceManagement is present |
| `createInteraction`, `updateInteraction`, `endInteraction`, `getUserConversation` | The `ChatsInteraction` lifecycle |
| `logIncident` | Log the case through `IIncidentManagement` (needs ServiceManagement) |
| `checkOnlineAgents`, `checkLiveChatAvailability`, `escalate`, `startAgentCommunication` | Agent hand-off |
| `addUserRating`, `serviceDeliveryRating` | Ratings |

Composer action to the shipped key that replaces it (from the chat module's own port notes):

| Composer class | Key |
| --- | --- |
| `CheckForOnlineAgentsDialogAction` | `checkOnlineAgents` |
| `CheckLiveChatAvailabilityDialogAction` | `checkLiveChatAvailability` |
| `EscalationDialogAction` | `escalate` |
| `StartCommunicationAgentDialogAction` | `startAgentCommunication` |
| `CheckIfStandAloneDialogAction` | `checkStandalone` |
| `DialogBot` (welcome check) | `shouldWelcome` |
| `GetCaseTypesDialog` | `getCaseTypes` (paging is now the choice node's `pageSize`) |
| `GetUserIdDialog` | `getContactNumber` |
| `GetMenuitemsDialogAction`, `MenuOptionsDialogAction` | `getMenuItems` (feeds a choice's `optionsFrom`) |
| `GetCurrentWebUserDialog` | `getWebUserProfile` |
| `GetuserInfoDialogAction` | `getUserInfo` |
| `UserHandlerDialogAction` | `saveUser` |
| `AdressDialogAction` | `resolveAddress` |
| `CreateInteractionDialogAction` | `createInteraction` |
| `UpdateInteractionDialogAction` | `updateInteraction` |
| `UpdateInteractionEndTimeDialogAction` | `endInteraction` |
| `GetUserConversationDialogAction` | `getUserConversation` |
| `LogIncidentDialogAction` | `logIncident` |
| `AddUserRatingDialogAction` | `addUserRating` |
| `ServiceDeliveryRatingDialogAction` | `serviceDeliveryRating` |
| `GetSubcategoryFilterDialogAction`, `GetCaseStatusFilterDialogAction` | `buildFilter` (builds the filter as an object, so customer input cannot alter it) |
| `GetRefListNameDialogAction` | `refListItemName` |

A project's own subclasses or copies of these were its own customisations: port the difference as a project action
that wraps or replaces the shipped one, rather than assuming the shipped behaviour is identical. The shipped actions
fixed some Composer defects (case category passed as the reference-list value, not the 0-based index; known customer's
details carried into the case); say so when a project's tests relied on the old behaviour.

This list is a snapshot. The source of truth is `GET api/bot-flows/actions` on a running host (key, params,
available/unavailable) and the `[FlowActionInfo]` attributes in the chat module. Check it before porting.

## Not shipped

At the time of writing, the chat module has no equivalent for: sending a WhatsApp Flow from an action and reading its
`nfm_reply` (use the `form` node and `IWhatsAppFormSource` instead), `ExtractFlowData`, case status lookup, file
upload, user verification, and the "Rating ..." reply handler. If the project needs one, port it as a project action
(or a candidate for the chat module, and say so to the user). Read the chat docs' known-gaps section for the current
list.
