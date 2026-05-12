---
name: shesha-workflow
description: Generates Shesha workflow artifacts for .NET applications using ABP framework with NHibernate. Creates workflow instances, definitions, managers, service tasks, extension methods, and FluentMigrator database migrations. Use when the user asks to create, scaffold, or update workflow-related classes, workflow steps, workflow conditions, or workflow database tables in a Shesha project.
---

# Shesha Workflow Code Generation

Generate workflow artifacts for a Shesha/.NET/ABP/NHibernate application based on $ARGUMENTS.

## Instructions

- Inspect nearby files to determine the correct namespace root.
- Use `Guid` as entity ID type. All domain properties must be `virtual`.
- Every workflow requires at minimum: Workflow Instance + Workflow Definition (domain layer).
- Generate a new GUID for `[DiscriminatorValue]` attributes.
- Place files according to the folder structure below.

## Artifact catalog

| # | Artifact | Layer | Template |
|---|----------|-------|----------|
| 1 | Workflow Instance | Domain | [domain-artifacts.md](domain-artifacts.md) §1 |
| 2 | Workflow Definition | Domain | [domain-artifacts.md](domain-artifacts.md) §2 |
| 3 | Workflow Manager | Domain | [domain-artifacts.md](domain-artifacts.md) §3 |
| 4 | Lifecycle Operations (Suspend/Resume/Cancel/Start) | Domain | [domain-artifacts.md](domain-artifacts.md) §4 |
| 5 | Batch Workflow Manager (cycle-based bulk initiation) | Domain | [domain-artifacts.md](domain-artifacts.md) §5 |
| 6 | Service Task | Application | [service-tasks.md](service-tasks.md) §1 |
| 7 | Service Task with Typed Arguments | Application | [service-tasks.md](service-tasks.md) §2 |
| 8 | Generic Base Service Task | Application | [service-tasks.md](service-tasks.md) §3 |
| 9 | External-System Await / Auto-Completion Helper | Application | [service-tasks.md](service-tasks.md) §4 |
| 10 | Workflow Extensions | Application | [service-tasks.md](service-tasks.md) §5 |
| 11 | Hangfire Background Job for Batch Initiation | Application | [service-tasks.md](service-tasks.md) §6 |
| 12 | Database Migration | Domain | [migrations.md](migrations.md) |
| 13 | Dashboard / Admin Queries | Application | [querying-and-dashboards.md](querying-and-dashboards.md) §5–§6 |
| 14 | View Entities (pre-built) | Domain (read-only) | [querying-and-dashboards.md](querying-and-dashboards.md) §2 |

**When generating multiple artifacts**, always create the Instance + Definition pair first, then add Service Tasks per workflow step.
**When building dashboard or admin views**, consult the [querying-and-dashboards.md](querying-and-dashboards.md) reference for pre-built view entities, query patterns, and application service examples.
**When debugging a running workflow instance**, use the `/analyze-workflow-state` skill instead — it parses ProcessState XML, fetches live data from the backend API, and diagnoses execution issues.

## Folder structure

```
{Module}.Domain/
  Domain/{WorkflowName}Workflows/
    {WorkflowName}Workflow.cs                   ← Instance (§1)
    {WorkflowName}WorkflowDefinition.cs         ← Definition (§2)
    {WorkflowName}WorkflowManager.cs            ← Manager + lifecycle ops (§3, §4)
    {WorkflowName}BatchWorkflowManager.cs       ← Batch manager when needed (§5)
  Migrations/
    M{YYYYMMDDHHmmss}.cs

{Module}.Application/
  Jobs/
    Initiate{WorkflowName}WorkflowsJob.cs       ← Hangfire background job (§6)
  Services/
    {ExternalSystem}/
      {ExternalSystem}WorkflowHelper.cs         ← External-trigger helper (§4)
  Workflows/
    Common/
      {TaskName}ServiceTaskBase.cs              ← Generic base task (§3)
    {WorkflowNamePlural}/
      {TaskName}ServiceTask.cs                  ← Service task (§1 or §2)
      {WorkflowName}WorkflowExtensions.cs       ← Extension methods (§5)
```

## Quick reference

### Base classes

| Artifact | Base Class |
|----------|-----------|
| Workflow Instance | `WorkflowInstanceWithTypedDefinition<TDefinition>` (`Shesha.Workflow.Domain`) |
| Workflow Definition | `WorkflowDefinition` |
| Workflow Manager | `DomainService` |
| Batch Workflow Manager | `DomainService` with generic params `<TDef, TInstance, TModel>` |
| Service Task | `AsyncServiceTask<TWorkflow>` + `ITransientDependency` |
| Service Task with Args | `AsyncServiceTask<TWorkflow, TArgs>` + `ITransientDependency` |
| Generic Base Task | `AsyncServiceTask<TWorkflow> where TWorkflow : WorkflowInstance` |
| Gateway condition ext. | `static class` on `WorkflowInstance` → returns `bool` |
| Action ext. methods | `static class` on typed `{WorkflowName}Workflow` → returns `Task` |
| Background Job | `ITransientDependency` (NOT `ScheduledJobBase`) |
| DB Migration | `Migration` or `OneWayMigration` |

### Key dependencies

| Interface / Class | Namespace | Use |
|-------------------|-----------|-----|
| `ServiceTaskExecutionContext<T>` | `Shesha.Workflow.Tasks` | Service task `RunAsync` parameter |
| `ServiceTaskExecutionContext<T, TArgs>` | `Shesha.Workflow.Tasks` | Typed-args task `RunAsync` parameter |
| `IProcessDomainService` | `Shesha.Workflow.DomainServices` | Start by name, complete user tasks |
| `ProcessAppService` | `Shesha.Workflow.AppServices.Processes` | Suspend / Resume / Cancel |
| `IWorkflowHelper` | `Shesha.Workflow` | Resume user task, emit message, get variables |
| `WorkflowExecutionLogItem` | `Shesha.Workflow.Domain` | External-trigger auto-completion |
| `IRepository<WorkflowInstance, Guid>` | `Abp.Domain.Repositories` | Manager manual instance creation |
| `ILogger<T>` | `Microsoft.Extensions.Logging` | Structured logging in service tasks |
| `WorkflowInstanceDashboardItem` | `Shesha.Workflow.Domain.ViewEntities` | Dashboard listing view entity |
| `WorkflowStatisticsItem` | `Shesha.Workflow.Domain.ViewEntities` | Step-level statistics with timing and decisions |
| `WorkflowInboxItem` | `Shesha.Workflow.Domain.ViewEntities` | User inbox (pending tasks) |
| `WorkflowSentItem` | `Shesha.Workflow.Domain.ViewEntities` | Completed tasks sent by user |
| `ProcessProgressItem` | `Shesha.Workflow.Domain.ViewEntities` | Step progress indicator for a workflow |
| `WorkflowTimelineItem` | `Shesha.Workflow.Domain.ViewEntities` | Timeline/audit trail view |

### Key attributes

| Attribute | Used On |
|-----------|---------|
| `[JoinedProperty("TableName")]` | Instance, Definition |
| `[Prefix(UsePrefixes = false)]` | Instance |
| `[Entity(TypeShortAlias = "...")]` | Instance |
| `[DiscriminatorValue("slug")]` | Definition |
| `[ServiceTaskArguments("slug")]` | Typed-args service task class |
| `[Display(Name, Description)]` | Definition, Service Task |
| `[Migration(YYYYMMDDHHmmss)]` | Migration class |

### Service task method signature

```csharp
// CORRECT — override RunAsync, return Task (void), access workflow via context
public override async Task RunAsync(ServiceTaskExecutionContext<{WorkflowName}Workflow> context)
{
    var workflow = context.WorkflowInstance;  // typed workflow instance
    // context.Pvc  →  IReadWriteVariables (process variable container)
    await _workflowRepository.UpdateAsync(workflow);
}

// With typed arguments:
public override async Task RunAsync(
    ServiceTaskExecutionContext<{WorkflowName}Workflow, {TaskName}Args> context)
{
    var workflow = context.WorkflowInstance;
    var args = context.Arguments;  // populated by the BPMN designer
}
```

### Common patterns

**Refresh workflow (NHibernate stale state fix):**
```csharp
var sessionProvider = StaticContext.IocManager.Resolve<ISessionProvider>();
sessionProvider.Session.Refresh(workflow);
```

**Sync SubStatus to Model Status:**
```csharp
workflow.Model.Status = ({RefListStatusEnum}?)workflow.SubStatus;
```

**Resolve dependency in extension methods:**
```csharp
var repo = IocManager.Instance.Resolve<IRepository<{Entity}, Guid>>();
```

**Check definition config in a service task:**
```csharp
if (workflow.Definition?.{ConfigFlag} != true)
    return; // feature disabled — skip silently
```

**Suspend a workflow:**
```csharp
await _processAppService.SuspendAsync(new SuspendProcessInput
{
    WorkflowInstanceId = workflowInstance.Id,
    Comments = "Paused pending external action"
});
```

**Resume a workflow:**
```csharp
await _processAppService.ResumeAsync(new ResumeProcessInput
{
    WorkflowInstanceId = workflowInstance.Id,
    Comments = "Resumed after external action completed"
});
```

**Cancel a workflow:**
```csharp
await _processAppService.CancelAsync(new CancelProcessInput
{
    WorkflowInstanceId = workflowInstance.Id,
    Comments = "Cancelled — reason here"
});
```

**Start a workflow by name (programmatic):**
```csharp
await _processDomainService.StartByNameAsync<{WorkflowDefinition}, {WorkflowInstance}>(
    new WorkflowDefinitionIdentifier({ModuleName}.Name, "{discriminator-slug}"),
    async (instance) =>
    {
        instance.Model = myEntity;
        instance.Subject = "Workflow subject text";
    });
```

**Auto-complete a workflow step from an external trigger:**
```csharp
// Find the active log item by step name, then complete it:
var logItem = _logItemRepo.GetAll()
    .FirstOrDefault(i => i.WorkflowTask.ActionText == stepName
                      && i.CompletedOn == null
                      && i.IsLast == true
                      && i.Status == RefListWorkflowLogItemStatus.Active);
if (logItem != null)
    await _workflowHelper.ResumeUserTaskAsync(logItem.WorkflowTask,
        new UserTaskResponse { Decision = "{decision-uid}", Comment = "Auto-completed" });
```

**Check active workflow guard:**
```csharp
var hasActive = await _workflowRepo.CountAsync(w =>
    w.Model.Id == modelId &&
    w.Status == RefListWorkflowStatus.InProgress) > 0;
if (hasActive)
    throw new UserFriendlyException("An active workflow already exists.");
```

**Enqueue batch initiation to Hangfire:**
```csharp
BackgroundJob.Enqueue<Initiate{WorkflowName}WorkflowsJob>(
    j => j.ExecuteAsync(initiateDto));
```

## Migration table naming

| Artifact | Table Name | FK Target |
|----------|-----------|-----------|
| Instance | `{Prefix}_{WorkflowName}Workflows` | `workflow.workflow_instances` |
| Definition | `{Prefix}_{WorkflowName}WorkflowDefinitions` | `workflow.workflow_definitions` |

Use the project's established module prefix (e.g. `Leave_`, `Pmds_`, `Hcm_`) — inspect nearby migrations to determine the correct prefix for the target module.

Now generate the requested workflow artifact(s) based on: $ARGUMENTS
