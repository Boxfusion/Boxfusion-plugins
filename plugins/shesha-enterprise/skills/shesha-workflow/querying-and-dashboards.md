# Querying Workflows for Dashboards, Admin Views, and Statistics

- [§1. Workflow Engine Data Model Overview](#1-workflow-engine-data-model-overview) — entities, views, and relationships
- [§2. Pre-Built Database Views](#2-pre-built-database-views) — view-backed entities for querying
- [§3. Core Table Entities for Deep Queries](#3-core-table-entities-for-deep-queries) — WorkflowInstance, WorkflowExecutionLogItem
- [§4. Reference List Enums](#4-reference-list-enums) — status, task type, log item status, priority
- [§5. Query Patterns](#5-query-patterns) — filtering by definition, step, outcome, timing, assignee
- [§6. Application Service Patterns](#6-application-service-patterns) — building dashboard and admin endpoints
- [§7. Existing API Endpoints](#7-existing-api-endpoints) — what ProcessAppService already exposes

---

## §1. Workflow Engine Data Model Overview

### Entity Relationship Summary

```
WorkflowDefinition (template)
  └── WorkflowInstance (running/completed execution)
        ├── WorkflowTask (BPMN task nodes: user task, service task, start event)
        │     └── UserTaskConfiguration (BPMN-designer config per task)
        │           └── UserTaskDecision (possible outcomes per user task)
        ├── WorkflowExecutionLogItem (activation + completion log per step)
        │     ├── WorkflowAssignee (individual person assignments)
        │     └── WorkflowHighLevelAssignee (role/team assignments)
        ├── WorkflowTodoItem (pending items awaiting human action)
        └── WorkflowInstanceState (serialised BPMN engine state)
```

### Key Timing Fields

| Entity | Field | Meaning |
|--------|-------|---------|
| `WorkflowInstance` | `SubmissionDate` | When workflow was started |
| `WorkflowInstance` | `CompletionDate` | When workflow finished |
| `WorkflowInstance` | `DueDate` | Expected completion date |
| `WorkflowExecutionLogItem` | `ActiveOn` | When the step became active |
| `WorkflowExecutionLogItem` | `CompletedOn` | When the step was completed (null = still active) |
| `WorkflowExecutionLogItem` | `OverdueDate` | SLA deadline for the step |
| `WorkflowExecutionLogItem` | `CheckpointDate` | Secondary milestone date |

**Step duration** = `CompletedOn - ActiveOn` (computed in query or in memory)
**Workflow duration** = `CompletionDate - SubmissionDate`

---

## §2. Pre-Built Database Views

The workflow engine provides read-only view-backed entities (`[ImMutable]`, `[SnakeCaseNaming]`) mapped to database views in the `workflow` schema. These are the recommended starting point for dashboards.

All view entities are auto-exposed via GraphQL and can be queried via `IRepository<T, Guid>`.

### WorkflowInstanceDashboardItem — Admin overview of all instances

**View:** `workflow.vw_workflow_instances_dashboard_items`
**Entity:** `Shesha.Workflow.Domain.WorkflowInstanceDashboardItem`
**Best for:** Admin views listing all workflow instances, filterable by definition, status, date, initiator.

```csharp
// Properties
Guid WorkflowInstanceId
Guid WorkflowDefinitionId
string ProcessName              // workflow definition name
string RefNumber                // e.g. "WF-001234"
string Subject                  // heading text
DateTime? InitiatedOn           // when started
Person Initiator                // FK to Person (who started it)
bool IsArchived
DateTime? LastExceptionTime     // last engine error (useful for monitoring)
```

### WorkflowStatisticsItem — Per-task statistics

**View:** `workflow.vw_workflow_statistics`
**Entity:** `Shesha.Workflow.Domain.WorkflowStatisticsItem`
**Best for:** Filtering by active step, step outcome, step timing. One row per task activation.

```csharp
// Properties
Guid WorkflowInstanceId
Guid TaskId
Guid? LogItemId
Guid? ParentTaskId              // for multi-instance body tasks
string Alias                    // BPMN element alias (used in code expressions)
string ActionText               // display label (e.g. "Approve Application")
bool IsCompleted
bool IsActive                   // true if step is currently active
bool IsTerminated
DateTime? ActiveOn              // when step was activated
DateTime? CompletedOn           // when step was completed
Person? CompletedByPerson       // FK — who completed it
string DecisionAlias            // outcome alias (e.g. "approved", "rejected")
MultiInstanceActivityType MultiInstanceType
RefListWorkflowTaskType TaskType // UserTask, ServiceTask, StartEvent, etc.
string ActivityId               // BPMN element ID
string? ActivityInstanceId
bool AllowSendBackToThisTask
```

### WorkflowTimelineItem — Full step history

**View:** `workflow.vw_workflow_log_items`
**Entity:** `Shesha.Workflow.Domain.WorkflowTimelineItem`
**Best for:** Timeline/history views showing all steps with timing and decisions.

```csharp
Guid WorkflowInstanceId
Guid TaskId
Guid? LogItemId
string ActionType               // e.g. "Draft", "Recommend", "Approve"
string ActionText               // display label
DateTime? ActiveOn
DateTime? CompletedOn
string DecisionText             // human-readable decision label
Person CompletedByPerson
bool IsActive                   // true if currently active
```

### ProcessProgressItem — Progress indicator

**View:** `workflow.vw_workflow_instance_progress_items`
**Entity:** `Shesha.Workflow.Domain.ProcessProgressItem`
**Best for:** Visual progress bars, step-by-step status with SLA tracking and assignees.

```csharp
Guid WorkflowInstanceId
string ActionText
DateTime CreatedOn
DateTime? ActivatedOn
DateTime? CompletedOn
DateTime? OverdueDate           // SLA deadline
string? DecisionTakenText
Guid? CompletedById
string? CompletedByFullName
RefListWorkflowLogItemStatus? Status  // Waiting, Active, CompletedByUser, etc.
decimal? SortIndex              // ordering
IList<ActiveUserTaskAssignee> CurrentAssignees  // who is currently assigned
IList<WorkflowHighLevelAssignee> TaskAssignees  // configured assignees
```

### WorkflowInboxItem — Person's pending tasks

**View:** `workflow.vw_inbox_items`
**Entity:** `Shesha.Workflow.Domain.WorkflowInboxItem`
**Extends:** `WorkflowFolderItemBase` (WorkflowInstanceId, WorkflowDefinitionId, ProcessName, RefNumber, Subject)

```csharp
Guid TodoId                     // the pending WorkflowTodoItem
string Initiator                // who started the workflow
string ActionText               // what needs to be done
bool UserHasOpened
DateTime ReceivedOn             // when it appeared in inbox
Guid PersonId                   // assigned person
Guid? PositionId
string? StatusFinalText         // SubStatus text with fallback to Status
```

### WorkflowSentItem — Person's completed tasks

**View:** `workflow.vw_sent_items`
**Entity:** `Shesha.Workflow.Domain.WorkflowSentItem`
**Extends:** `WorkflowFolderItemBase`

```csharp
DateTime CompletedOn
string Initiator
string ActionText               // step name
string DecisionTakenText        // what decision was made
Guid? PersonId
Guid? PositionId
string? StatusFinalText
```

### WorkflowMyItem — Initiator's own workflows

**View:** `workflow.vw_my_items`
**Entity:** `Shesha.Workflow.Domain.WorkflowMyItem`
**Extends:** `WorkflowFolderItemBase`

```csharp
DateTime? InitiatedOn
Guid? PersonId
Guid? PositionId
bool IsArchived
string? StatusFinalText
string? CurrentTask             // string_agg of active task names
```

### WorkflowDraftItem — Draft workflows

**View:** `workflow.vw_draft_items`
**Entity:** `Shesha.Workflow.Domain.WorkflowDraftItem`
**Extends:** `WorkflowFolderItemBase`

```csharp
DateTime CreatedOn
Guid PersonId
Guid? PositionId
```

### ActiveUserTaskAssignee — Current assignees per task

**View:** `workflow.vw_active_task_assignees`
**Entity:** `Shesha.Workflow.Domain.ActiveUserTaskAssignee`

```csharp
Guid WorkflowTaskId
Guid ExecutionLogItemId
string DisplayName
Guid PersonId
```

### WorkflowFolderItemBase — Shared base for folder views

```csharp
// Inherited by InboxItem, SentItem, MyItem, DraftItem
Guid WorkflowInstanceId
Guid WorkflowDefinitionId
string ProcessName
string RefNumber
string Subject
RefListPriority Priority        // [NotMapped]
```

---

## §3. Core Table Entities for Deep Queries

Use these when the views don't provide enough detail (e.g. custom joins, SLA analysis, assignee tracking).

### WorkflowInstance — `workflow.workflow_instances`

```csharp
// Key queryable properties
Guid Id
string? RefNumber               // [StringLength(300)]
string Subject
Person? SubmittedBy             // initiator
DateTime? SubmissionDate        // start time
RefListWorkflowStatus? Status   // Draft, InProgress, Completed, Cancelled, Suspended
Int64? SubStatus                // custom per-definition status
DateTime? CompletionDate        // end time (for reporting)
DateTime? DueDate               // expected completion
bool IsArchived
WorkflowDefinition WorkflowDefinition  // FK to definition
// Inherited: CreationTime, CreatorUserId, LastModificationTime, IsDeleted
```

### WorkflowExecutionLogItem — `workflow.workflow_execution_log_items`

The most detailed entity for step-level analysis. One record per step activation.

```csharp
WorkflowInstance WorkflowInstance   // FK
WorkflowExecutionLogItem? PreviousLogItem  // chain of steps
Person? ActivatedByPerson
DateTime? ActiveOn                  // when step became active
DateTime? OverdueDate               // SLA deadline
DateTime? CheckpointDate            // secondary milestone
DateTime? CompletedOn               // when completed (null = active)
Person? CompletedByPerson
Person? CompletedByImpersonatorPerson
Position? CompletedByPosition
WorkflowAssignee? CompletedByAssignee
WorkflowHighLevelAssignee? CompletedByHighLevelAssignee
string? UserComments
bool IsLast                         // true for current/latest log item per task
WorkflowTask WorkflowTask           // FK to task (has ActionText, Alias, TaskId)
UserTaskDecision? DecisionTaken     // FK to decision (has Name, Label, Alias)
RefListWorkflowLogItemStatus Status // Waiting, Active, CompletedByUser, Terminated, etc.
```

### WorkflowTask — `workflow.workflow_tasks`

```csharp
WorkflowInstance WorkflowInstance
WorkflowTask? ParentTask            // for multi-instance body tasks
string TaskId                       // BPMN element ID
string? ActionType                  // e.g. "Draft", "Recommend", "Approve"
string? ActionText                  // display label
decimal? SortIndexOnProgressIndicator
bool HideFromProgressIndicator
// Discriminator subtypes: WorkflowUserTask, WorkflowServiceTask, WorkflowStartEvent
```

### UserTaskDecision — `workflow.user_task_decisions`

```csharp
string Uid                          // unique within the BPMN diagram
string Name
string? Label
string? Description
string? Alias                       // used in code (e.g. "approved", "rejected")
int SortOrder
UserTaskConfigurationBase UserTask  // FK to task configuration
```

---

## §4. Reference List Enums

### RefListWorkflowStatus — Instance lifecycle

```csharp
[ReferenceList("WorkflowStatus")]
enum RefListWorkflowStatus : Int64
{
    Draft = 1,          // #b4b4b4 grey
    InProgress = 2,     // #428bca blue
    Completed = 3,      // #87d068 green
    Cancelled = 4,      // #d9534f red
    Suspended = 5,      // #bfbfbf light grey
}
```

### RefListWorkflowLogItemStatus — Step execution status

```csharp
[ReferenceList("WorkflowLogItemStatus")]
enum RefListWorkflowLogItemStatus
{
    Waiting = 0,
    Active = 1,
    CompletedByUser = 2,
    Terminated = 3,
    Reassigned = 4,
    SentBack = 5,
    Suspended = 6,
    CompletedByAnonym = 7,
}
```

### RefListWorkflowTaskType — BPMN element types

```csharp
[ReferenceList("WorkflowTaskType")]
enum RefListWorkflowTaskType : Int64
{
    Unknown = 0,
    StartEvent = 1,
    UserTask = 2,
    UserTaskMultiInstanceBody = 3,
    ServiceTask = 4,
    ServiceTaskMultiInstanceBody = 5,
}
```

### RefListPriority — Workflow priority

```csharp
[ReferenceList("Priority")]
enum RefListPriority : Int64
{
    Normal = 1, Medium = 2, High = 3, Urgent = 4,
}
```

### RefListProcessableEntityStatus — Common model status

```csharp
[ReferenceList("ProcessableEntityStatus")]
enum RefListProcessableEntityStatus : Int64
{
    Draft = 1, InProgress = 2, Approved = 3, Declined = 4,
    Retracted = 5, Cancelled = 6, TakenOver = 7,
    PartiallyApproved = 8, Withdrawn = 9, Parked = 10, Printed = 11
}
```

### RefListSLAModel — SLA calculation modes

```csharp
[ReferenceList("SLAModel")]
enum RefListSLAModel : Int64
{
    None = 1, BusinessDays = 2, CalendarDays = 3,
    BusinessHours = 4, Hours = 5, BusinessDaysFromPreviousStep = 6
}
```

---

## §5. Query Patterns

All queries use standard NHibernate `IRepository<T, Guid>` injection. View entities are read-only.

### (a) List all instances of a specific workflow definition

```csharp
// Using the dashboard view (recommended for admin screens)
var items = _dashboardItemRepo.GetAll()
    .Where(i => i.WorkflowDefinitionId == targetDefinitionId)
    .OrderByDescending(i => i.InitiatedOn);

// Filter by status
var active = items.Where(i => i.Status_lkp == (long)RefListWorkflowStatus.InProgress);

// Filter by date range
var recent = items.Where(i => i.InitiatedOn >= startDate && i.InitiatedOn <= endDate);
```

### (b) Filter by current active step (step name or alias)

```csharp
// Find all instances currently at a specific step
var instancesAtStep = _statsRepo.GetAll()
    .Where(s => s.IsActive && s.ActionText == "Approve Application")
    .Select(s => s.WorkflowInstanceId)
    .Distinct();

// By BPMN alias
var byAlias = _statsRepo.GetAll()
    .Where(s => s.IsActive && s.Alias == "approveApplication");

// Join: dashboard items currently at a specific step
var query = from dash in _dashboardItemRepo.GetAll()
            join stat in _statsRepo.GetAll()
                on dash.WorkflowInstanceId equals stat.WorkflowInstanceId
            where dash.WorkflowDefinitionId == definitionId
                && stat.IsActive
                && stat.ActionText == "Initiate Verification"
            select new
            {
                dash.RefNumber,
                dash.Subject,
                dash.Initiator,
                dash.InitiatedOn,
                stat.ActiveOn,
            };
```

### (c) Filter by step outcome / decision

```csharp
// All completed steps with a specific decision
var approved = _statsRepo.GetAll()
    .Where(s => s.IsCompleted && s.DecisionAlias == "approved");

// Via execution log for richer data (including who and when)
var decisions = _logItemRepo.GetAll()
    .Where(e => e.WorkflowInstance.WorkflowDefinition.Id == definitionId)
    .Where(e => e.DecisionTaken != null && e.DecisionTaken.Alias == "rejected")
    .Select(e => new
    {
        e.WorkflowInstance.RefNumber,
        DecisionBy = e.CompletedByPerson.FullName,
        e.CompletedOn,
        e.UserComments
    });
```

### (d) Step duration / timing analysis

```csharp
// Duration per step across all instances of a definition
var stepTimings = _logItemRepo.GetAll()
    .Where(e => e.WorkflowInstance.WorkflowDefinition.Id == definitionId)
    .Where(e => e.CompletedOn != null)
    .Select(e => new
    {
        StepName = e.WorkflowTask.ActionText,
        e.ActiveOn,
        e.CompletedOn,
        // Duration computed in memory: CompletedOn - ActiveOn
        e.OverdueDate,
        IsOverdue = e.OverdueDate != null && e.CompletedOn > e.OverdueDate,
        Decision = e.DecisionTaken != null ? e.DecisionTaken.Label : null,
        CompletedBy = e.CompletedByPerson != null ? e.CompletedByPerson.FullName : null,
        e.Status
    });

// Total workflow duration
var workflowDurations = _instanceRepo.GetAll()
    .Where(i => i.WorkflowDefinition.Id == definitionId && i.CompletionDate != null)
    .Select(i => new
    {
        i.RefNumber,
        i.SubmissionDate,
        i.CompletionDate,
        // Duration = CompletionDate - SubmissionDate
    });

// Average step time (fetch then compute in memory)
var stepData = stepTimings.ToList();
var avgByStep = stepData
    .Where(s => s.ActiveOn.HasValue && s.CompletedOn.HasValue)
    .GroupBy(s => s.StepName)
    .Select(g => new
    {
        StepName = g.Key,
        Count = g.Count(),
        AvgDuration = TimeSpan.FromTicks((long)g.Average(s =>
            (s.CompletedOn.Value - s.ActiveOn.Value).Ticks)),
        MaxDuration = g.Max(s => s.CompletedOn.Value - s.ActiveOn.Value),
        OverdueCount = g.Count(s => s.IsOverdue),
    });
```

### (e) SLA / overdue tracking

```csharp
// Currently overdue steps
var overdue = _logItemRepo.GetAll()
    .Where(e => e.IsLast
        && e.CompletedOn == null
        && e.OverdueDate != null
        && e.OverdueDate < DateTime.Now
        && e.Status == RefListWorkflowLogItemStatus.Active);

// Overdue with workflow context
var overdueDetails = from log in _logItemRepo.GetAll()
                     join inst in _instanceRepo.GetAll()
                         on log.WorkflowInstance.Id equals inst.Id
                     where log.IsLast
                         && log.CompletedOn == null
                         && log.OverdueDate < DateTime.Now
                         && log.Status == RefListWorkflowLogItemStatus.Active
                         && inst.WorkflowDefinition.Id == definitionId
                     select new
                     {
                         inst.RefNumber,
                         inst.Subject,
                         StepName = log.WorkflowTask.ActionText,
                         log.ActiveOn,
                         log.OverdueDate,
                         DaysOverdue = (DateTime.Now - log.OverdueDate.Value).Days
                     };
```

### (f) Inbox / assigned items for a person

```csharp
// Current inbox (pending tasks)
var inbox = _inboxRepo.GetAll()
    .Where(i => i.PersonId == currentPersonId)
    .OrderByDescending(i => i.ReceivedOn);

// Filter inbox by workflow type
var filteredInbox = inbox
    .Where(i => i.WorkflowDefinitionId == targetDefinitionId);

// Completed items by a person
var sent = _sentItemRepo.GetAll()
    .Where(i => i.PersonId == currentPersonId)
    .OrderByDescending(i => i.CompletedOn);

// Filter by decision taken
var approvedBySelf = sent
    .Where(i => i.DecisionTakenText == "Approved");
```

### (g) My workflows (initiator view)

```csharp
var myItems = _myItemRepo.GetAll()
    .Where(i => i.PersonId == currentPersonId)
    .OrderByDescending(i => i.InitiatedOn);

// Filter by current step
var atVerification = myItems
    .Where(i => i.CurrentTask != null && i.CurrentTask.Contains("Verification"));
```

### (h) Progress indicator for a single instance

```csharp
var progress = _progressRepo.GetAll()
    .Where(p => p.WorkflowInstanceId == instanceId)
    .OrderBy(p => p.SortIndex ?? 0)
    .ThenBy(p => p.CreatedOn);
// Includes: ActionText, ActivatedOn, CompletedOn, OverdueDate, Status,
//           CompletedByFullName, CurrentAssignees, TaskAssignees
```

### (i) Workflow status counts (dashboard summary)

```csharp
var statusCounts = _dashboardItemRepo.GetAll()
    .Where(i => i.WorkflowDefinitionId == definitionId)
    .GroupBy(i => i.Status_lkp)
    .Select(g => new { Status = g.Key, Count = g.Count() })
    .ToList();

// Active step distribution
var stepDistribution = _statsRepo.GetAll()
    .Where(s => s.IsActive)
    .Join(_dashboardItemRepo.GetAll().Where(d => d.WorkflowDefinitionId == definitionId),
        s => s.WorkflowInstanceId,
        d => d.WorkflowInstanceId,
        (s, d) => s.ActionText)
    .GroupBy(action => action)
    .Select(g => new { StepName = g.Key, Count = g.Count() })
    .ToList();
```

### (j) Querying typed workflow instances (with Model properties)

```csharp
// When you need to filter by properties on the typed workflow or its Model entity:
var typedQuery = _typedWorkflowRepo.GetAll()
    .Where(w => w.Status == RefListWorkflowStatus.InProgress)
    .Where(w => w.Model.ApplicationType == RefListApplicationType.Entity)
    .Where(w => w.Model.Account.Id == accountId)
    .Select(w => new
    {
        w.Id,
        w.RefNumber,
        w.Subject,
        w.SubmissionDate,
        ModelName = w.Model.Name,
        AccountName = w.Model.Account.Name
    });
```

---

## §6. Application Service Patterns

### (a) Dashboard stats endpoint

```csharp
using Abp.Application.Services;
using Abp.Domain.Repositories;
using Shesha.Workflow.Domain;
using Shesha.Workflow.Domain.Enums;
using System;
using System.Linq;
using System.Threading.Tasks;

namespace {ModuleNamespace}.Application.Services
{
    public class {WorkflowName}DashboardAppService : ApplicationService
    {
        private readonly IRepository<WorkflowInstanceDashboardItem, Guid> _dashboardRepo;
        private readonly IRepository<WorkflowStatisticsItem, Guid> _statsRepo;
        private readonly IRepository<WorkflowExecutionLogItem, Guid> _logItemRepo;
        private readonly IRepository<{WorkflowName}Workflow, Guid> _workflowRepo;

        public {WorkflowName}DashboardAppService(
            IRepository<WorkflowInstanceDashboardItem, Guid> dashboardRepo,
            IRepository<WorkflowStatisticsItem, Guid> statsRepo,
            IRepository<WorkflowExecutionLogItem, Guid> logItemRepo,
            IRepository<{WorkflowName}Workflow, Guid> workflowRepo)
        {
            _dashboardRepo = dashboardRepo;
            _statsRepo = statsRepo;
            _logItemRepo = logItemRepo;
            _workflowRepo = workflowRepo;
        }

        /// <summary>
        /// Summary counts for dashboard cards (total, active, completed, overdue, etc.)
        /// </summary>
        public async Task<DashboardSummaryDto> GetSummaryAsync(Guid definitionId)
        {
            var all = _dashboardRepo.GetAll()
                .Where(i => i.WorkflowDefinitionId == definitionId);

            var overdueCount = _logItemRepo.GetAll()
                .Where(e => e.IsLast
                    && e.CompletedOn == null
                    && e.OverdueDate < DateTime.Now
                    && e.Status == RefListWorkflowLogItemStatus.Active
                    && e.WorkflowInstance.WorkflowDefinition.Id == definitionId)
                .Count();

            return new DashboardSummaryDto
            {
                Total = all.Count(),
                Active = all.Count(i => i.Status_lkp == (long)RefListWorkflowStatus.InProgress),
                Completed = all.Count(i => i.Status_lkp == (long)RefListWorkflowStatus.Completed),
                Cancelled = all.Count(i => i.Status_lkp == (long)RefListWorkflowStatus.Cancelled),
                Overdue = overdueCount,
            };
        }

        /// <summary>
        /// Average duration per step for a specific workflow definition.
        /// </summary>
        public async Task<List<StepDurationDto>> GetStepDurationsAsync(Guid definitionId)
        {
            var items = _logItemRepo.GetAll()
                .Where(e => e.WorkflowInstance.WorkflowDefinition.Id == definitionId
                    && e.CompletedOn != null
                    && e.ActiveOn != null)
                .Select(e => new
                {
                    StepName = e.WorkflowTask.ActionText,
                    ActiveOn = e.ActiveOn.Value,
                    CompletedOn = e.CompletedOn.Value,
                    IsOverdue = e.OverdueDate != null && e.CompletedOn > e.OverdueDate,
                })
                .ToList();

            return items.GroupBy(e => e.StepName)
                .Select(g => new StepDurationDto
                {
                    StepName = g.Key,
                    Count = g.Count(),
                    AvgDurationHours = g.Average(e =>
                        (e.CompletedOn - e.ActiveOn).TotalHours),
                    MaxDurationHours = g.Max(e =>
                        (e.CompletedOn - e.ActiveOn).TotalHours),
                    OverdueCount = g.Count(e => e.IsOverdue),
                })
                .OrderBy(d => d.StepName)
                .ToList();
        }
    }

    public class DashboardSummaryDto
    {
        public int Total { get; set; }
        public int Active { get; set; }
        public int Completed { get; set; }
        public int Cancelled { get; set; }
        public int Overdue { get; set; }
    }

    public class StepDurationDto
    {
        public string StepName { get; set; }
        public int Count { get; set; }
        public double AvgDurationHours { get; set; }
        public double MaxDurationHours { get; set; }
        public int OverdueCount { get; set; }
    }
}
```

### (b) Admin listing with combined filters

```csharp
/// <summary>
/// Admin view: list workflow instances with current step, assignee, and timing.
/// Supports filtering by definition, status, current step, date range, and model properties.
/// </summary>
public async Task<List<WorkflowAdminItemDto>> GetAdminListAsync(WorkflowAdminFilterInput input)
{
    // Base query on typed workflow for model access
    var query = _workflowRepo.GetAll()
        .Where(w => !w.IsDeleted);

    // Filter by status
    if (input.Status.HasValue)
        query = query.Where(w => w.Status == input.Status.Value);

    // Filter by date range
    if (input.FromDate.HasValue)
        query = query.Where(w => w.SubmissionDate >= input.FromDate.Value);
    if (input.ToDate.HasValue)
        query = query.Where(w => w.SubmissionDate <= input.ToDate.Value);

    // Filter by model property (e.g. account)
    if (input.AccountId.HasValue)
        query = query.Where(w => w.Model.Account.Id == input.AccountId.Value);

    var instances = query.ToList();
    var instanceIds = instances.Select(w => w.Id).ToList();

    // Get current active steps for all matching instances
    var activeSteps = _statsRepo.GetAll()
        .Where(s => s.IsActive && instanceIds.Contains(s.WorkflowInstanceId))
        .ToList()
        .GroupBy(s => s.WorkflowInstanceId)
        .ToDictionary(g => g.Key, g => g.First());

    // Optionally filter by current step name
    if (!string.IsNullOrEmpty(input.CurrentStepName))
    {
        var atStep = activeSteps
            .Where(kvp => kvp.Value.ActionText == input.CurrentStepName)
            .Select(kvp => kvp.Key)
            .ToHashSet();
        instances = instances.Where(w => atStep.Contains(w.Id)).ToList();
    }

    return instances.Select(w =>
    {
        activeSteps.TryGetValue(w.Id, out var step);
        return new WorkflowAdminItemDto
        {
            Id = w.Id,
            RefNumber = w.RefNumber,
            Subject = w.Subject,
            Status = w.Status,
            SubmissionDate = w.SubmissionDate,
            CompletionDate = w.CompletionDate,
            CurrentStep = step?.ActionText,
            CurrentStepActiveSince = step?.ActiveOn,
        };
    }).ToList();
}
```

---

## §7. Existing API Endpoints

The `ProcessAppService` at route `/api/services/SheshaWorkflow/Process` already provides:

| Method | Endpoint | Purpose | Response uses |
|--------|----------|---------|---------------|
| GET | `UserTasks` | All tasks for an instance | `WorkflowStatisticsItem` |
| GET | `TimeLine` | Full timeline with audit trail | `WorkflowTimelineItem` |
| GET | `Progress` | Progress indicator with timing | `ProcessProgressItem` |
| GET | `Details` | Full instance model | `WorkflowInstance` |
| GET | `MyActiveTodoItems` | Current user's pending items | `WorkflowTodoItem` |
| GET | `AvailableDefinitions` | Startable workflow definitions | `WorkflowDefinition` |

The `WorkflowAppService` at `/api/services/SheshaWorkflow/Workflow` provides:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `{id}/PastTimeLine` | Completed timeline items |

All view entities are also auto-queryable via **GraphQL** — no custom endpoints needed for basic list/filter/sort.

### GraphQL example (frontend)

```graphql
{
  workflowInstanceDashboardItems(
    filter: "workflowDefinitionId == \"<guid>\""
    sorting: "initiatedOn desc"
    maxResultCount: 50
  ) {
    items {
      workflowInstanceId
      processName
      refNumber
      subject
      initiatedOn
      initiator { fullName }
      isArchived
    }
    totalCount
  }
}
```

```graphql
{
  workflowStatisticsItems(
    filter: "workflowInstanceId == \"<guid>\" && isActive == true"
  ) {
    items {
      actionText
      alias
      activeOn
      completedOn
      decisionAlias
      isActive
      isCompleted
    }
  }
}
```

---

## Quick Reference: Which entity to use when

| Use Case | Entity | Key Filter Fields |
|----------|--------|-------------------|
| Admin list of all instances | `WorkflowInstanceDashboardItem` | WorkflowDefinitionId, Status_lkp, InitiatedOn, IsArchived |
| Current step per instance | `WorkflowStatisticsItem` | WorkflowInstanceId, IsActive, ActionText, Alias |
| Step outcomes/decisions | `WorkflowStatisticsItem` or `WorkflowExecutionLogItem` | DecisionAlias, DecisionTaken |
| Step timing/duration | `WorkflowExecutionLogItem` | ActiveOn, CompletedOn, OverdueDate |
| Total workflow duration | `WorkflowInstance` | SubmissionDate, CompletionDate |
| SLA/overdue monitoring | `WorkflowExecutionLogItem` | IsLast, CompletedOn==null, OverdueDate < Now |
| Person's inbox | `WorkflowInboxItem` | PersonId, WorkflowDefinitionId |
| Person's completed work | `WorkflowSentItem` | PersonId, DecisionTakenText, CompletedOn |
| Initiator's own workflows | `WorkflowMyItem` | PersonId, CurrentTask |
| Progress bar / stepper | `ProcessProgressItem` | WorkflowInstanceId, SortIndex |
| Step history/timeline | `WorkflowTimelineItem` | WorkflowInstanceId, ActiveOn, CompletedOn |
| Current assignees | `ActiveUserTaskAssignee` | WorkflowTaskId, PersonId |
| Model-property filters | Typed `{Name}Workflow` repo | Model.*, Status, SubmissionDate |
