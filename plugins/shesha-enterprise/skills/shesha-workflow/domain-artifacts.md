# Domain Layer Workflow Artifacts

- [§1. Workflow Instance](#1-workflow-instance) — entity being tracked by the workflow
- [§2. Workflow Definition](#2-workflow-definition) — configuration + `CreateInstance()` factory
- [§3. Workflow Manager](#3-workflow-manager) — orchestration, status sync, guards
- [§4. Lifecycle Operations](#4-workflow-lifecycle-operations-suspend--resume--cancel--start) — suspend/resume/cancel/start
- [§5. Batch Workflow Manager](#5-batch-workflow-manager-cycle-based-bulk-initiation) — cycle-based bulk initiation

---

## §1. Workflow Instance

**File:** `{WorkflowName}Workflow.cs` in `Domain/{WorkflowName}Workflows/`

```csharp
using Shesha.Domain.Attributes;
using Shesha.Workflow.Domain;
using System.ComponentModel.DataAnnotations;

namespace {ModuleNamespace}.Domain.{WorkflowName}Workflows
{
    [JoinedProperty("{TablePrefix}_{WorkflowName}Workflows")]
    [Prefix(UsePrefixes = false)]
    [Entity(TypeShortAlias = "{ModuleNamespace}.Domain.{WorkflowName}Workflow")]
    public class {WorkflowName}Workflow : WorkflowInstanceWithTypedDefinition<{WorkflowName}WorkflowDefinition>
    {
        public virtual {ModelEntity} Model { get; set; }
    }
}
```

**With multiple entity references** (e.g. owner + model + related entities):

```csharp
[JoinedProperty("{TablePrefix}_{WorkflowName}Workflows")]
[Prefix(UsePrefixes = false)]
[Entity(TypeShortAlias = "{ModuleNamespace}.Domain.{WorkflowName}Workflow")]
public class {WorkflowName}Workflow : WorkflowInstanceWithTypedDefinition<{WorkflowName}WorkflowDefinition>
{
    public virtual {OwnerEntity} PartOf { get; set; }
    public virtual {ModelEntity} Model { get; set; }
    public virtual {RelatedEntity1} Lead { get; set; }
    public virtual {RelatedEntity2} Opportunity { get; set; }
}
```

**With extra state** (e.g. cancellation context):

```csharp
[JoinedProperty("{TablePrefix}_{WorkflowName}Workflows")]
[Prefix(UsePrefixes = false)]
[Entity(TypeShortAlias = "{ModuleNamespace}.Domain.{WorkflowName}Workflow")]
public class {WorkflowName}Workflow : WorkflowInstanceWithTypedDefinition<{WorkflowName}WorkflowDefinition>
{
    public virtual {ModelEntity} Model { get; set; }
    public virtual bool ApplicationWasRecommended { get; set; }
    public virtual bool ApplicationWasApproved { get; set; }

    [StringLength(4000)]
    public virtual string Comments { get; set; }
}
```

**Key rules:**
- `Model` links to the entity being processed — it is the primary required FK
- Additional FK references (`PartOf`, `Lead`, `Opportunity`, etc.) are allowed when the workflow needs to track multiple related entities
- Do NOT add tracking dates, flags, or notes to the workflow instance; state is managed via `SubStatus`, gateway conditions, and the `Model` entity itself
- Add extra non-FK properties only for workflow-engine state that cannot live on the model (e.g. a single `Comments` string or a recommended/approved flag needed by gateway conditions)
- `[JoinedProperty]` maps to a dedicated DB table (joined subclass)
- `[Prefix(UsePrefixes = false)]` disables column prefix generation
- All properties must be `virtual`

---

## §2. Workflow Definition

**File:** `{WorkflowName}WorkflowDefinition.cs` in `Domain/{WorkflowName}Workflows/`

Always generated alongside a Workflow Instance — they are a mandatory pair.

```csharp
using Shesha.Domain.Attributes;
using Shesha.Workflow.Domain;
using System.ComponentModel.DataAnnotations;

namespace {ModuleNamespace}.Domain.{WorkflowName}Workflows
{
    [DiscriminatorValue("{discriminator-slug}")]
    [JoinedProperty("{TablePrefix}_{WorkflowName}WorkflowDefinitions")]
    [Display(Name = "{Friendly Name} workflow definition")]
    public class {WorkflowName}WorkflowDefinition : WorkflowDefinition
    {
        public override WorkflowInstance CreateInstance()
        {
            return new {WorkflowName}Workflow
            {
                WorkflowDefinition = this,
                RefNumber = AssignReferenceNumber(),
                SubStatus = (long){RefListStatusEnum}.Draft,
                Model = new {ModelEntity}()
            };
        }
    }
}
```

**With session-based initialization** (when model creation needs the current user):

```csharp
public override WorkflowInstance CreateInstance()
{
    var abpSession = StaticContext.IocManager.Resolve<IAbpSession>();
    var userId = abpSession.GetUserId();

    return new {WorkflowName}Workflow
    {
        WorkflowDefinition = this,
        RefNumber = AssignReferenceNumber(),
        Model = new {ModelEntity}
        {
            CreatorUserId = userId,
            // ... other initialization
        }
    };
}
```

Use `StaticContext.IocManager.Resolve<T>()` (not `IocManager.Instance`) inside `WorkflowDefinition.CreateInstance()` — `IocManager.Instance` is for static extension methods.

**With linked owner entity creation** (when the model is owned by a parent entity that must also be created):

```csharp
public override WorkflowInstance CreateInstance()
{
    var abpSession = StaticContext.IocManager.Resolve<IAbpSession>();
    var userId = abpSession.GetUserId();

    var owner = new {OwnerEntity}
    {
        Name = $"{Descriptive name}"
    };

    return new {WorkflowName}Workflow
    {
        WorkflowDefinition = this,
        RefNumber = AssignReferenceNumber(),
        Model = new {ModelEntity}
        {
            PartOf = owner
        }
    };
}
```

Use this when the model entity requires a parent/owner entity (`PartOf`) that is created in the same transaction as the workflow. The owner entity is instantiated first, then referenced on the model — NHibernate will cascade-insert both when the unit of work flushes.

**With processor-based initialization** (complex model setup):

```csharp
public override WorkflowInstance CreateInstance()
{
    var processor = IocManager.Instance.Resolve<{ModelEntity}Processor>();
    var model = AsyncHelper.RunSync(() => processor.InitialiseAsync<{ModelEntity}>());

    return new {WorkflowName}Workflow
    {
        WorkflowDefinition = this,
        RefNumber = AssignReferenceNumber(),
        SubStatus = (long){RefListStatusEnum}.Draft,
        Model = model
    };
}
```

**`CreateInstance()` is ALWAYS required** — it is how the Shesha workflow engine instantiates a new workflow run. Never omit it.

**Rules:**
1. Create the matching Workflow Instance type
2. Set `WorkflowDefinition = this`
3. Assign reference number via `AssignReferenceNumber()`
4. Optionally set `SubStatus` to the initial status (e.g. Draft) if a status RefList exists

**With configuration properties** (SLA settings, feature flags — combined with `CreateInstance()`):

```csharp
[DiscriminatorValue("{discriminator-slug}")]
[JoinedProperty("{TablePrefix}_{WorkflowName}WorkflowDefinitions")]
[Display(Name = "{Friendly Name} Workflow", Description = "{Description}")]
public class {WorkflowName}WorkflowDefinition : WorkflowDefinition
{
    public override WorkflowInstance CreateInstance()
    {
        return new {WorkflowName}Workflow
        {
            WorkflowDefinition = this,
            RefNumber = AssignReferenceNumber()
        };
    }

    // SLA / timeout settings
    public virtual int {TimeoutName}Days { get; set; } = {DefaultDays};
    public virtual int {SLAName}Days { get; set; } = {DefaultDays};

    // Feature flags
    public virtual bool {FeatureFlag} { get; set; } = true;

    // Notification settings
    public virtual bool Send{NotificationType}Notifications { get; set; } = true;
    public virtual int {NotificationType}NotificationDays { get; set; } = {DefaultDays};
}
```

Configuration properties are referenced from service tasks via `workflow.Definition?.{PropertyName}`.

---

## §3. Workflow Manager

**File:** `{WorkflowName}WorkflowManager.cs` in `Domain/{WorkflowName}Workflows/`

Generate when user needs workflow orchestration, status management, or cross-workflow coordination.

```csharp
using Abp.Domain.Repositories;
using Abp.Domain.Services;
using Abp.Domain.Uow;
using Abp.Runtime.Session;
using Abp.UI;
using Shesha.NHibernate;
using Shesha.Workflow.Domain;
using Shesha.Workflow.Domain.Enums;
using Shesha.Workflow.DomainServices;
using System;
using System.Linq;
using System.Threading.Tasks;

namespace {ModuleNamespace}.Domain.{WorkflowName}Workflows
{
    public class {WorkflowName}WorkflowManager : DomainService
    {
        private readonly IRepository<{WorkflowName}Workflow, Guid> _workflowRepository;
        private readonly IRepository<{ModelEntity}, Guid> _modelRepository;
        private readonly IAbpSession _abpSession;
        private readonly ISessionProvider _sessionProvider;
        private readonly IProcessDomainService _processDomainService;

        public {WorkflowName}WorkflowManager(
            IRepository<{WorkflowName}Workflow, Guid> workflowRepository,
            IRepository<{ModelEntity}, Guid> modelRepository,
            IAbpSession abpSession,
            ISessionProvider sessionProvider,
            IProcessDomainService processDomainService)
        {
            _workflowRepository = workflowRepository;
            _modelRepository = modelRepository;
            _abpSession = abpSession;
            _sessionProvider = sessionProvider;
            _processDomainService = processDomainService;
        }

        public async Task<string> CreateSubjectAsync(Guid workflowId)
        {
            var workflow = await _workflowRepository.GetAsync(workflowId);
            var model = workflow.Model
                ?? throw new ArgumentNullException(nameof(workflow.Model));
            return $"{model.Name} — {model.Person?.FullName}";
        }

        public async Task UpdateStatusesAsync(
            Guid workflowId,
            {RefListStatusEnum} subStatus,
            {RefListStatusEnum} modelStatus)
        {
            try
            {
                var workflow = await _workflowRepository.GetAsync(workflowId);
                workflow.SubStatus = (long?)subStatus;
                workflow.Model.Status = modelStatus;
                await _workflowRepository.UpdateAsync(workflow);
            }
            catch (Exception ex)
            {
                Logger.Error($"Failed to update statuses for workflow {workflowId}", ex);
                throw;
            }
        }

        public void RefreshWorkflow({WorkflowName}Workflow workflow)
        {
            _sessionProvider.Session.Refresh(workflow);
        }
    }
}
```

**Manager with manual instance creation** (when definition has no `CreateInstance()` — uses direct repository insert):

```csharp
public class {WorkflowName}WorkflowManager : DomainService
{
    private readonly IRepository<{WorkflowName}Workflow, Guid> _workflowRepository;
    private readonly IRepository<{WorkflowName}WorkflowDefinition, Guid> _definitionRepository;
    private readonly IRepository<{ModelEntity}, Guid> _modelRepository;

    public {WorkflowName}WorkflowManager(
        IRepository<{WorkflowName}Workflow, Guid> workflowRepository,
        IRepository<{WorkflowName}WorkflowDefinition, Guid> definitionRepository,
        IRepository<{ModelEntity}, Guid> modelRepository)
    {
        _workflowRepository = workflowRepository;
        _definitionRepository = definitionRepository;
        _modelRepository = modelRepository;
    }

    public virtual async Task<{WorkflowName}Workflow> StartAsync(Guid modelId)
    {
        var model = await _modelRepository.GetAsync(modelId);

        // Guard: no duplicate active workflow
        var existing = _workflowRepository.GetAll()
            .Where(w => w.Model.Id == modelId
                     && w.Status != RefListWorkflowStatus.Cancelled
                     && w.Status != RefListWorkflowStatus.Completed)
            .FirstOrDefault();
        if (existing != null)
            throw new UserFriendlyException($"Active workflow already exists for '{model.Name}'.");

        var definition = await _definitionRepository.GetAll()
            .Where(d => d.IsLast)
            .FirstOrDefaultAsync()
            ?? throw new UserFriendlyException("{WorkflowName} workflow definition not configured.");

        var workflow = new {WorkflowName}Workflow
        {
            Model = model,
            WorkflowDefinition = definition,
            Status = RefListWorkflowStatus.InProgress,
            Subject = $"{Friendly Name} - {model.Name}"
        };

        await _workflowRepository.InsertAsync(workflow);
        await CurrentUnitOfWork.SaveChangesAsync();
        return workflow;
    }

    public virtual async Task<{WorkflowName}Workflow> GetActiveAsync(Guid modelId)
    {
        return _workflowRepository.GetAll()
            .Where(w => w.Model.Id == modelId
                     && w.Status == RefListWorkflowStatus.InProgress)
            .OrderByDescending(w => w.CreationTime)
            .FirstOrDefault();
    }

    public virtual async Task EnsureNoActiveWorkflowAsync(Guid modelId)
    {
        if (await GetActiveAsync(modelId) != null)
            throw new UserFriendlyException("An active workflow already exists.");
    }
}
```

**For generic/reusable managers** (extending a framework base):

```csharp
public class {WorkflowName}WorkflowManager
    : FrameworkWorkflowManager<{WorkflowName}WorkflowDefinition, {WorkflowName}Workflow, {ModelEntity}>
{
    public {WorkflowName}WorkflowManager(/* base params */) : base(/* pass through */) { }
}
```

**Manager responsibilities:** subject generation, status sync between `SubStatus` and model `Status`, NHibernate session refresh, cross-workflow coordination, duplicate active workflow guard, completing user tasks via `IProcessDomainService`.

---

## §4. Workflow Lifecycle Operations (Suspend / Resume / Cancel / Start)

Add these methods to any `{WorkflowName}WorkflowManager` that needs to control workflow state programmatically.
All operations guard against invalid state transitions before calling the engine.

```csharp
using Shesha.Workflow.AppServices.Processes;
using Shesha.Workflow.AppServices.Processes.Dto;
using Shesha.Workflow.Domain.Enums;

// ── Injected dependencies ──────────────────────────────────────────────────────
private readonly ProcessAppService _processAppService;
private readonly IRepository<WorkflowInstance, Guid> _workflowInstanceRepo;

// ── Suspend (pause an in-progress workflow) ────────────────────────────────────
public async Task SuspendWorkflowAsync(Guid workflowInstanceId, string comments = "")
{
    var instance = await _workflowInstanceRepo.GetAsync(workflowInstanceId);
    if (instance.Status != RefListWorkflowStatus.InProgress)
        throw new UserFriendlyException("Only in-progress workflows can be suspended.");

    await _processAppService.SuspendAsync(new SuspendProcessInput
    {
        WorkflowInstanceId = instance.Id,
        Comments = comments
    });
}

// Bulk suspend — e.g. close all workflows for a cycle
public async Task SuspendAllAsync(IEnumerable<Guid> workflowInstanceIds, string comments = "")
{
    foreach (var id in workflowInstanceIds)
    {
        var instance = await _workflowInstanceRepo.GetAsync(id);
        if (instance.Status == RefListWorkflowStatus.InProgress)
            await _processAppService.SuspendAsync(new SuspendProcessInput
            {
                WorkflowInstanceId = id,
                Comments = comments
            });
    }
}

// ── Resume (un-pause a suspended workflow) ─────────────────────────────────────
public async Task ResumeWorkflowAsync(Guid workflowInstanceId, string comments = "")
{
    var instance = await _workflowInstanceRepo.GetAsync(workflowInstanceId);
    if (instance.Status != RefListWorkflowStatus.Suspended
        && instance.Status != RefListWorkflowStatus.Draft)
        throw new UserFriendlyException("Only suspended or draft workflows can be resumed.");

    await _processAppService.ResumeAsync(new ResumeProcessInput
    {
        WorkflowInstanceId = instance.Id,
        Comments = comments
    });
}

// ── Cancel (permanently end a workflow) ───────────────────────────────────────
public async Task CancelWorkflowAsync(Guid workflowInstanceId, string comments = "")
{
    var instance = await _workflowInstanceRepo.GetAsync(workflowInstanceId);
    if (instance.Status != RefListWorkflowStatus.InProgress
        && instance.Status != RefListWorkflowStatus.Suspended)
        throw new UserFriendlyException("Only in-progress or suspended workflows can be cancelled.");

    await _processAppService.CancelAsync(new CancelProcessInput
    {
        WorkflowInstanceId = instance.Id,
        Comments = comments
    });
}

// ── Start a child/related workflow by name ─────────────────────────────────────
public async Task<Guid> StartChildWorkflowAsync(
    {ChildWorkflow}Workflow parentWorkflow,
    string comments = "")
{
    var definitionId = new WorkflowDefinitionIdentifier(
        {ChildModule}.ModuleName,
        "{child-workflow-discriminator-slug}");

    return await _processDomainService.StartByNameAsync<
        {ChildWorkflowDefinition},
        {ChildWorkflow}Workflow>(
        definitionId,
        async (instance) =>
        {
            instance.Model = parentWorkflow.Model.{ChildEntity};
            instance.Subject = parentWorkflow.Subject;
            // Set any other properties needed by the child workflow
        });
}
```

**Status transition guard pattern** — check before any write operation that depends on workflow state:

```csharp
public async Task<bool> HasActiveWorkflowAsync(Guid modelId)
{
    return await _workflowRepository.CountAsync(w =>
        w.Model.Id == modelId &&
        w.Status == RefListWorkflowStatus.InProgress) > 0;
}

// Guard in an app service before allowing a new action:
if (await _workflowManager.HasActiveWorkflowAsync(modelId))
    throw new UserFriendlyException(
        "Action not allowed while a workflow is in progress.");
```

---

## §5. Batch Workflow Manager (Cycle-Based Bulk Initiation)

Use when a single user action (e.g. "open a performance cycle") must create workflow instances for many entities in parallel.
This pattern belongs in the Domain layer because it orchestrates domain entities; the Application layer only exposes it via app services and Hangfire jobs.

```csharp
using Abp.Domain.Repositories;
using Abp.Domain.Services;
using Abp.Domain.Uow;
using Shesha.Workflow.DomainServices;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace {ModuleNamespace}.Domain.{WorkflowName}Workflows
{
    public class {WorkflowName}WorkflowManager<TWorkflowDefinition, TWorkflow, TModel>
        : DomainService
        where TWorkflowDefinition : {WorkflowName}WorkflowDefinitionBase
        where TWorkflow : {WorkflowName}WorkflowBase<TModel>
        where TModel : {ModelEntity}
    {
        private const int DefaultBatchSize = 1;
        private const int DefaultMaxDegreeOfParallelism = 10;

        private readonly IRepository<TModel, Guid> _modelRepository;
        private readonly IRepository<TWorkflow, Guid> _workflowRepository;
        private readonly IProcessDomainService _processDomainService;
        private readonly IUnitOfWorkManager _unitOfWorkManager;

        public {WorkflowName}WorkflowManager(
            IRepository<TModel, Guid> modelRepository,
            IRepository<TWorkflow, Guid> workflowRepository,
            IProcessDomainService processDomainService,
            IUnitOfWorkManager unitOfWorkManager)
        {
            _modelRepository = modelRepository;
            _workflowRepository = workflowRepository;
            _processDomainService = processDomainService;
            _unitOfWorkManager = unitOfWorkManager;
        }

        /// <summary>Entry point — retrieves eligible entities and initiates workflows in batches.</summary>
        public async Task ProcessCycleAsync({CycleEntity} cycle, long? creatorUserId = null)
        {
            var eligibleModels = await _modelRepository.GetAll()
                .Where(m => m.Cycle.Id == cycle.Id && !m.WorkflowStarted)
                .ToListAsync();

            await ProcessEntitiesInBatchesAsync(eligibleModels, creatorUserId);
        }

        private async Task ProcessEntitiesInBatchesAsync(
            IList<TModel> models,
            long? creatorUserId,
            int batchSize = DefaultBatchSize,
            int maxParallelism = DefaultMaxDegreeOfParallelism)
        {
            var semaphore = new SemaphoreSlim(maxParallelism);

            var tasks = models.Chunk(batchSize).Select(async batch =>
            {
                await semaphore.WaitAsync();
                try
                {
                    foreach (var model in batch)
                    {
                        using var uow = _unitOfWorkManager.Begin();
                        await CreateWorkflowForEntityAsync(model, creatorUserId);
                        await uow.CompleteAsync();
                    }
                }
                finally
                {
                    semaphore.Release();
                }
            });

            await Task.WhenAll(tasks);
        }

        private async Task CreateWorkflowForEntityAsync(TModel model, long? creatorUserId)
        {
            // Guard: skip if an active workflow already exists
            var existing = _workflowRepository.GetAll()
                .FirstOrDefault(w => w.Model.Id == model.Id
                                  && w.Status == RefListWorkflowStatus.InProgress);
            if (existing != null)
                return;

            var definitionId = new WorkflowDefinitionIdentifier(
                {ModuleName}.Name,
                "{workflow-discriminator-slug}");

            await _processDomainService.StartByNameAsync<TWorkflowDefinition, TWorkflow>(
                definitionId,
                async (instance) =>
                {
                    instance.Model = model;
                    instance.Subject = $"{model.Name} — {model.Person?.FullName}";
                    if (creatorUserId.HasValue)
                        instance.CreatorUserId = creatorUserId;
                });

            model.WorkflowStarted = true;
            await _modelRepository.UpdateAsync(model);
        }

        /// <summary>Suspend all in-progress workflows for a cycle (e.g. "close a cycle").</summary>
        public async Task CloseWorkflowsAsync(
            Guid cycleId,
            ProcessAppService processAppService,
            string comments = "Cycle closed")
        {
            var workflows = await _workflowRepository.GetAll()
                .Where(w => w.Model.Cycle.Id == cycleId
                         && w.Status == RefListWorkflowStatus.InProgress)
                .ToListAsync();

            foreach (var wf in workflows)
                await processAppService.SuspendAsync(new SuspendProcessInput
                {
                    WorkflowInstanceId = wf.Id,
                    Comments = comments
                });
        }

        /// <summary>Resume all suspended workflows for a cycle (e.g. "reopen a cycle").</summary>
        public async Task ReopenWorkflowsAsync(
            Guid cycleId,
            ProcessAppService processAppService,
            string comments = "Cycle reopened")
        {
            var workflows = await _workflowRepository.GetAll()
                .Where(w => w.Model.Cycle.Id == cycleId
                         && w.Status == RefListWorkflowStatus.Suspended)
                .ToListAsync();

            foreach (var wf in workflows)
                await processAppService.ResumeAsync(new ResumeProcessInput
                {
                    WorkflowInstanceId = wf.Id,
                    Comments = comments
                });
        }
    }
}
```

**Concrete specialization** (subclass with fixed generic params for a specific module):

```csharp
public class {Module}{WorkflowName}WorkflowManager
    : {WorkflowName}WorkflowManager<
        {Module}{WorkflowName}WorkflowDefinition,
        {Module}{WorkflowName}Workflow,
        {Module}{ModelEntity}>
{
    public {Module}{WorkflowName}WorkflowManager(/* same params as base */) : base(/* pass through */) { }
}
```

**Key rules:**
- Keep `DefaultBatchSize = 1` and `DefaultMaxDegreeOfParallelism = 10` as starting defaults; tune per domain requirements
- Each entity in a batch runs in its own `IUnitOfWorkManager.Begin()` so one failure doesn't block the rest
- Guard against duplicate active workflows before calling `StartByNameAsync`
- Mark `model.WorkflowStarted = true` (or equivalent flag) after successful start to make the operation idempotent
