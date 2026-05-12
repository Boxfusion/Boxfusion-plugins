# Application Layer Workflow Artifacts

- [§1. Service Task](#1-service-task) — single automated workflow step
- [§2. Service Task with Typed Arguments](#2-service-task-with-typed-arguments) — designer-configurable args
- [§3. Generic Base Service Task](#3-generic-base-service-task) — shared logic across workflow types
- [§4. External-System Await / Auto-Completion Helper](#4-external-system-await--auto-completion-helper) — park + resume from external trigger
- [§5. Workflow Extension Methods](#5-workflow-extension-methods) — gateway conditions + action helpers
- [§6. Hangfire Background Job](#6-hangfire-background-job-for-batch-workflow-initiation) — batch initiation offloading

---

## §1. Service Task

**File:** `{TaskName}ServiceTask.cs` in `Workflows/{WorkflowNamePlural}/`

A single automated step in a workflow. The engine instantiates and executes it when reaching the matching BPMN node.

```csharp
using Abp.Dependency;
using Abp.Domain.Repositories;
using Microsoft.Extensions.Logging;
using Shesha.Workflow.Domain;
using Shesha.Workflow.Tasks;
using System;
using System.ComponentModel.DataAnnotations;
using System.Threading.Tasks;

namespace {ModuleNamespace}.Application.Workflows.{WorkflowNamePlural}
{
    [Display(Name = "{Friendly Task Name}",
             Description = "{Brief description}")]
    public class {TaskName}ServiceTask : AsyncServiceTask<{WorkflowName}Workflow>, ITransientDependency
    {
        private readonly IRepository<{WorkflowName}Workflow, Guid> _workflowRepository;
        private readonly ILogger<{TaskName}ServiceTask> _logger;

        public {TaskName}ServiceTask(
            IRepository<{WorkflowName}Workflow, Guid> workflowRepository,
            ILogger<{TaskName}ServiceTask> logger)
        {
            _workflowRepository = workflowRepository;
            _logger = logger;
        }

        public override async Task RunAsync(ServiceTaskExecutionContext<{WorkflowName}Workflow> context)
        {
            var workflow = context.WorkflowInstance;

            // Task logic here

            await _workflowRepository.UpdateAsync(workflow);
        }
    }
}
```

**Key rules:**
- Override `RunAsync`, NOT `ExecuteAsync` or `Run`
- Return type is `Task` (void — no bool return)
- Access the workflow instance via `context.WorkflowInstance`
- Access process variables via `context.Pvc` (`IReadWriteVariables`)
- `AsyncServiceTask<T>` is in `Shesha.Workflow.Tasks`
- Always implement `ITransientDependency` so ABP registers it automatically

### Common task patterns

**(a) Update Model Status (sync SubStatus → Model):**
```csharp
public override async Task RunAsync(ServiceTaskExecutionContext<{WorkflowName}Workflow> context)
{
    var workflow = context.WorkflowInstance;
    RefreshWorkflow(workflow);
    workflow.Model.Status = ({RefListStatusEnum}?)workflow.SubStatus;
    await _workflowRepository.UpdateAsync(workflow);
}

private void RefreshWorkflow({WorkflowName}Workflow workflow)
{
    var sessionProvider = StaticContext.IocManager.Resolve<ISessionProvider>();
    sessionProvider.Session.Refresh(workflow);
}
```

**(b) Update Subject:**
```csharp
public override async Task RunAsync(ServiceTaskExecutionContext<{WorkflowName}Workflow> context)
{
    var workflow = context.WorkflowInstance;
    RefreshWorkflow(workflow);
    if (workflow.Subject == null)
        workflow.Subject = await _workflowManager.CreateSubjectAsync(workflow.Id);
    await _workflowRepository.UpdateAsync(workflow);
}
```

**(c) Business Logic Delegation:**
```csharp
public override async Task RunAsync(ServiceTaskExecutionContext<{WorkflowName}Workflow> context)
{
    var workflow = context.WorkflowInstance;
    var model = workflow.Model
        ?? throw new InvalidOperationException("Workflow model is null");
    await _businessManager.ProcessAsync(model.Id);
}
```

**(d) Cross-Workflow Action (cancel a parent workflow from a child):**
```csharp
public override async Task RunAsync(ServiceTaskExecutionContext<{CancellationWorkflow}Workflow> context)
{
    var workflow = context.WorkflowInstance;
    RefreshWorkflow(workflow);

    var originalWorkflow = await _originalWorkflowRepository.GetAll()
        .Where(w => w.Model.Id == workflow.Model.Parent.Id
                  && w.Status == RefListWorkflowStatus.InProgress)
        .FirstOrDefaultAsync()
        ?? throw new ArgumentNullException("Original workflow not found");

    await _processAppService.CancelAsync(new CancelProcessInput
    {
        WorkflowInstanceId = originalWorkflow.Id,
        Comments = "Cancelled by approved cancellation request"
    });
    await _workflowManager.UpdateStatusesAsync(
        workflow.Id, RefListStatus.Cancelled, RefListStatus.Cancelled);
}
```

**(e) Spawn a Child Workflow from a Service Task:**
```csharp
public override async Task RunAsync(ServiceTaskExecutionContext<{WorkflowName}Workflow> context)
{
    var workflow = context.WorkflowInstance;

    var definitionId = new WorkflowDefinitionIdentifier(
        {ChildModule}.Name,
        "{child-workflow-discriminator-slug}");

    await _processDomainService.StartByNameAsync<{ChildWorkflowDef}, {ChildWorkflow}>(
        definitionId,
        async (childInstance) =>
        {
            childInstance.Model = workflow.Model.ChildModel;
            childInstance.Subject = workflow.Subject;
            childInstance.ParentWorkflowId = workflow.Id;
        });
}
```

**(f) With structured logging and error handling:**
```csharp
public override async Task RunAsync(ServiceTaskExecutionContext<{WorkflowName}Workflow> context)
{
    var workflow = context.WorkflowInstance;
    try
    {
        _logger.LogInformation("Processing {RefNumber}", workflow.RefNumber ?? "Unknown");

        // business logic

        await _workflowRepository.UpdateAsync(workflow);
        _logger.LogInformation("Completed for {RefNumber}", workflow.RefNumber);
    }
    catch (Exception ex)
    {
        _logger.LogError(ex, "Error processing {RefNumber}", workflow.RefNumber);
        throw;
    }
}
```

**(g) Check definition config before acting:**
```csharp
public override async Task RunAsync(ServiceTaskExecutionContext<{WorkflowName}Workflow> context)
{
    var workflow = context.WorkflowInstance;

    if (workflow.Definition?.{ConfigFlag} != true)
    {
        _logger.LogInformation("{ConfigFlag} is disabled — skipping");
        return;
    }

    // conditional logic
    await _workflowRepository.UpdateAsync(workflow);
}
```

**(h) Read/write process variables (Pvc):**
```csharp
public override async Task RunAsync(ServiceTaskExecutionContext<{WorkflowName}Workflow> context)
{
    var workflow = context.WorkflowInstance;

    // Read a variable set by a previous task or gateway
    var someFlag = context.Pvc.Get<bool>("{variableName}");

    // Set a variable for a downstream task or gateway condition
    context.Pvc.Set("{outputVariable}", someComputedValue);

    await _workflowRepository.UpdateAsync(workflow);
}
```

---

## §2. Service Task with Typed Arguments

**File:** `{TaskName}ServiceTask.cs` in `Workflows/{WorkflowNamePlural}/`

Use when a task needs configuration injected by the BPMN designer (e.g. a target status code). Arguments are stored in the workflow definition and supplied to the task at runtime.

```csharp
using Shesha.Workflow.Tasks;
using System.ComponentModel.DataAnnotations;
using System.Threading.Tasks;

namespace {ModuleNamespace}.Application.Workflows.{WorkflowNamePlural}
{
    [ServiceTaskArguments("{arguments-discriminator-slug}")]
    [Display(Name = "{Friendly Task Name}", Description = "{Brief description}")]
    public class {TaskName}ServiceTask
        : AsyncServiceTask<{WorkflowName}Workflow, {TaskName}Args>, ITransientDependency
    {
        private readonly IRepository<{WorkflowName}Workflow, Guid> _workflowRepository;

        public {TaskName}ServiceTask(IRepository<{WorkflowName}Workflow, Guid> workflowRepository)
        {
            _workflowRepository = workflowRepository;
        }

        public override async Task RunAsync(
            ServiceTaskExecutionContext<{WorkflowName}Workflow, {TaskName}Args> context)
        {
            var workflow = context.WorkflowInstance;
            var args = context.Arguments;

            // e.g. workflow.Model.Status = args.TargetStatus;
            await _workflowRepository.UpdateAsync(workflow);
        }
    }

    public class {TaskName}Args
    {
        public {RefListStatusEnum}? TargetStatus { get; set; }
        // Add other designer-configurable properties here
    }
}
```

**Key rules:**
- `[ServiceTaskArguments("slug")]` links the args class to the BPMN designer form
- Arguments are populated by the workflow designer, not by code
- Access via `context.Arguments` — never null (always initialized to `new()`)
- The args class must have a public parameterless constructor

---

## §3. Generic Base Service Task

**File:** `{TaskName}ServiceTaskBase.cs` in `Workflows/Common/`

Abstract base for tasks sharing logic across multiple workflow types (Template Method pattern).
Use when two or more workflows need the same service task but differ only in how they expose the model.

```csharp
using Abp.Dependency;
using Abp.Domain.Repositories;
using Shesha.Workflow.Domain;
using Shesha.Workflow.Tasks;
using System;
using System.Threading.Tasks;

namespace {ModuleNamespace}.Application.Workflows.Common
{
    public abstract class {TaskName}ServiceTaskBase<TWorkflow> : AsyncServiceTask<TWorkflow>, ITransientDependency
        where TWorkflow : WorkflowInstance
    {
        private readonly IRepository<{ModelEntity}, Guid> _modelRepository;

        protected {TaskName}ServiceTaskBase(IRepository<{ModelEntity}, Guid> modelRepository)
        {
            _modelRepository = modelRepository;
        }

        protected abstract {ModelEntity} GetModel(TWorkflow workflow);

        public override async Task RunAsync(ServiceTaskExecutionContext<TWorkflow> context)
        {
            var workflow = context.WorkflowInstance;
            var model = GetModel(workflow)
                ?? throw new InvalidOperationException($"Model is null on workflow {workflow.Id}");

            // Shared business logic here
        }
    }
}
```

**Concrete implementation** per workflow type:

**File:** `{TaskName}ServiceTask.cs` in `Workflows/{WorkflowNamePlural}/`

```csharp
using Abp.Domain.Repositories;
using {ModuleNamespace}.Application.Workflows.Common;
using System;

namespace {ModuleNamespace}.Application.Workflows.{WorkflowNamePlural}
{
    public class {TaskName}ServiceTask : {TaskName}ServiceTaskBase<{WorkflowName}Workflow>
    {
        public {TaskName}ServiceTask(IRepository<{ModelEntity}, Guid> modelRepository)
            : base(modelRepository)
        {
        }

        protected override {ModelEntity} GetModel({WorkflowName}Workflow workflow)
            => workflow.Model;
    }
}
```

---

## §4. External-System Await / Auto-Completion Helper

**File:** `{ExternalSystem}WorkflowHelper.cs` in `Services/{ExternalSystem}/`

Use when a workflow must park at a step until an external system (e.g. a government integration, file import) sends back a response. The helper is called by the import service to auto-advance the workflow.

```csharp
using Abp.Dependency;
using Abp.Domain.Repositories;
using Shesha.NHibernate;
using Shesha.Workflow.Domain;
using Shesha.Workflow.Domain.Enums;
using Shesha.Workflow;
using System;
using System.Linq;
using System.Threading.Tasks;

namespace {ModuleNamespace}.Application.Services.{ExternalSystem}
{
    public class {ExternalSystem}WorkflowHelper : ITransientDependency
    {
        private readonly IRepository<WorkflowExecutionLogItem, Guid> _logItemRepository;
        private readonly IWorkflowHelper _workflowHelper;

        public {ExternalSystem}WorkflowHelper(
            IRepository<WorkflowExecutionLogItem, Guid> logItemRepository,
            IWorkflowHelper workflowHelper)
        {
            _logItemRepository = logItemRepository;
            _workflowHelper = workflowHelper;
        }

        /// <summary>
        /// Finds and completes the named pending step on a workflow instance.
        /// Called when the external system returns a response.
        /// </summary>
        /// <param name="workflowInstanceId">The ID of the workflow instance to advance.</param>
        /// <param name="stepName">
        /// The exact "Action Text" value configured on the BPMN task node to complete.
        /// </param>
        public async Task GetAndCompleteStepAsync(Guid workflowInstanceId, string stepName)
        {
            // Find the active log item for the named step on this workflow instance
            var logItem = _logItemRepository.GetAll()
                .FirstOrDefault(item =>
                    item.WorkflowInstance.Id == workflowInstanceId &&
                    item.WorkflowTask.ActionText == stepName &&
                    item.CompletedOn == null &&
                    item.IsLast == true &&
                    item.Status == RefListWorkflowLogItemStatus.Active);

            if (logItem == null)
                return; // Step not active — nothing to complete

            var decision = new UserTaskResponse
            {
                Decision = "{decision-uid}",
                Comment = "Auto-completed by external system response"
            };

            await _workflowHelper.ResumeUserTaskAsync(logItem.WorkflowTask, decision);
        }
    }
}
```

**Pattern notes:**
- Called from the external system import service (e.g. a file import app service or scheduled job)
- Query `WorkflowExecutionLogItem` by: `ActionText == stepName`, `CompletedOn == null`, `IsLast == true`, `Status == Active`
- Use `IWorkflowHelper.ResumeUserTaskAsync(workflowTask, response)` to complete
- The BPMN step's "Action Text" property must exactly match `stepName`

---

## §5. Workflow Extension Methods

**File:** `{WorkflowName}WorkflowExtensions.cs` in `Workflows/{WorkflowNamePlural}/`

Two patterns — choose based on use case.

### (A) Gateway conditions — extend `WorkflowInstance`

Used by the workflow engine for routing decisions at BPMN gateways. Must extend the base `WorkflowInstance` type so the engine can call it from BPMN JSON expressions.

```csharp
using Abp.Dependency;
using Abp.Domain.Repositories;
using Shesha.Workflow.Domain;
using System;
using System.Linq;

namespace {ModuleNamespace}.Application.Workflows.{WorkflowNamePlural}
{
    public static class {WorkflowName}WorkflowExtensions
    {
        // Condition evaluated at a BPMN exclusive gateway
        public static bool {ConditionName}(this WorkflowInstance workflow)
        {
            if (workflow == null)
                throw new ArgumentNullException(nameof(workflow));

            var workflowRepo = IocManager.Instance
                .Resolve<IRepository<{WorkflowName}Workflow, Guid>>();

            var typedWorkflow = workflowRepo.FirstOrDefault(workflow.Id);
            if (typedWorkflow?.Model == null)
                return false;

            return typedWorkflow.Model.{SomeProperty} == {SomeValue};
        }

        // Reading a flag from the definition (configured per-deployment)
        public static bool {ConfigFlag}(this WorkflowInstance workflow)
        {
            var workflowRepo = IocManager.Instance
                .Resolve<IRepository<{WorkflowName}Workflow, Guid>>();
            var typedWorkflow = workflowRepo.FirstOrDefault(workflow.Id)
                ?? throw new InvalidOperationException($"Workflow {workflow?.Id} not found");

            var definitionRepo = IocManager.Instance
                .Resolve<IRepository<{WorkflowName}WorkflowDefinition, Guid>>();
            var definition = definitionRepo.FirstOrDefault(typedWorkflow.WorkflowDefinition.Id);

            return definition?.{ConfigFlag} ?? false;
        }
    }
}
```

### (B) Action methods and state queries — extend typed workflow

For programmatic use from service tasks, managers, or application services. Extends the specific workflow type directly.

```csharp
using Abp.Dependency;
using Abp.Domain.Repositories;
using System;
using System.Threading.Tasks;

namespace {ModuleNamespace}.Application.Workflows.{WorkflowNamePlural}
{
    public static class {WorkflowName}WorkflowExtensions
    {
        // State-mutating action (async)
        public static async Task {ActionName}Async(this {WorkflowName}Workflow workflow, string reason = null)
        {
            var repo = IocManager.Instance.Resolve<IRepository<{WorkflowName}Workflow, Guid>>();
            workflow.{StateProperty} = "{NewValue}";
            workflow.{DateProperty} = DateTime.Now;
            if (!string.IsNullOrEmpty(reason))
                workflow.Notes = $"{workflow.Notes}\n\n{DateTime.Now:yyyy-MM-dd HH:mm}: {reason}".Trim();
            await repo.UpdateAsync(workflow);
        }

        // Derived state check (bool — can also be used as gateway condition on typed workflow)
        public static bool {IsCondition}(this {WorkflowName}Workflow workflow)
        {
            if (!workflow.{DateProperty}.HasValue)
                return false;

            var thresholdDays = workflow.Definition?.{ThresholdConfig} ?? {DefaultDays};
            return DateTime.Now > workflow.{DateProperty}.Value.AddDays(thresholdDays);
        }

        // Computed value
        public static int? {ComputedValue}(this {WorkflowName}Workflow workflow)
        {
            if (!workflow.{DateProperty}.HasValue)
                return null;
            return (workflow.{DateProperty}.Value - DateTime.Now).Days;
        }
    }
}
```

**Key rules:**
- Gateway conditions (Pattern A): extend `WorkflowInstance`, return `bool`, use `IocManager.Instance.Resolve<T>()`, defensive null-checks returning `false`
- Action methods (Pattern B): extend the typed workflow, return `Task`, use `IocManager.Instance.Resolve<T>()` for repos
- Name boolean methods as questions: `IsConsentExpired`, `ShouldSendExpiryNotification`
- Name action methods as verbs: `GrantConsentAsync`, `DeclineConsentAsync`

---

## §6. Hangfire Background Job for Batch Workflow Initiation

**File:** `Initiate{WorkflowName}WorkflowsJob.cs` in `Jobs/`

Use when initiating many workflow instances (e.g. for all employees in a cycle) from an HTTP endpoint — offload to Hangfire to avoid request timeouts.

```csharp
using Abp.Dependency;
using Abp.Domain.Uow;
using System.Threading.Tasks;

namespace {ModuleNamespace}.Application.Jobs
{
    public class Initiate{WorkflowName}WorkflowsJob : ITransientDependency
    {
        private readonly {WorkflowName}WorkflowManager _manager;
        private readonly IUnitOfWorkManager _unitOfWorkManager;

        public Initiate{WorkflowName}WorkflowsJob(
            {WorkflowName}WorkflowManager manager,
            IUnitOfWorkManager unitOfWorkManager)
        {
            _manager = manager;
            _unitOfWorkManager = unitOfWorkManager;
        }

        [UnitOfWork]
        public virtual async Task ExecuteAsync({InitiateDto} dto)
        {
            using var uow = _unitOfWorkManager.Begin();
            await _manager.ProcessCycleAsync(dto);
            await uow.CompleteAsync();
        }
    }
}
```

**Enqueue from the app service:**
```csharp
// In the app service — enqueue instead of awaiting inline:
BackgroundJob.Enqueue<Initiate{WorkflowName}WorkflowsJob>(
    j => j.ExecuteAsync(initiateDto));
```

**Key rules:**
- Implements `ITransientDependency` — NOT a `ScheduledJobBase` (this is a one-shot background job, not a recurring schedule)
- Wrap execution in `IUnitOfWorkManager.Begin()` for transaction management
- The app service enqueues and returns immediately; the job runs asynchronously
- Use when initiation count could cause HTTP timeout (typically > ~20 workflows)
