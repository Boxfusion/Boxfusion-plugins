# Workflow Database Migrations

FluentMigrator migrations for workflow tables. Always generate alongside a new Instance + Definition pair.

**File:** `M{YYYYMMDDHHmmss}.cs` in `Migrations/`

## (a) Basic workflow tables

Minimum migration for any new workflow — creates both tables and links to the workflow engine's base tables.

```csharp
using FluentMigrator;

namespace {ModuleNamespace}.Domain.Migrations
{
    [Migration({YYYYMMDDHHmmss})]
    public class M{YYYYMMDDHHmmss} : Migration
    {
        public override void Up()
        {
            Create.Table("{Prefix}_{WorkflowName}Workflows")
                .WithIdAsGuid()
                .WithFullAuditColumns()
                .WithForeignKeyColumn("ModelId", "{ModelTableName}").Nullable();

            Create.Table("{Prefix}_{WorkflowName}WorkflowDefinitions")
                .WithIdAsGuid();

            Create.ForeignKey("fk_{Prefix}_{WorkflowName}WorkflowDefinitions_config_item")
                .FromTable("{Prefix}_{WorkflowName}WorkflowDefinitions")
                .ForeignColumn("Id")
                .ToTable("workflow_definitions").InSchema("workflow")
                .PrimaryColumn("id");

            Create.ForeignKey("fk_{Prefix}_{WorkflowName}Workflows_wf_inst")
                .FromTable("{Prefix}_{WorkflowName}Workflows")
                .ForeignColumn("Id")
                .ToTable("workflow_instances").InSchema("workflow")
                .PrimaryColumn("id");
        }

        public override void Down()
        {
            Delete.Table("{Prefix}_{WorkflowName}WorkflowDefinitions");
            Delete.Table("{Prefix}_{WorkflowName}Workflows");
        }
    }
}
```

**Rules:**
- `.WithFullAuditColumns()` on Instance table only, NOT on Definition table
- Definition table only needs `.WithIdAsGuid()`
- Both tables MUST have FKs to the `workflow` schema
- FK naming: `fk_{Prefix}_{Name}Workflows_wf_inst` and `fk_{Prefix}_{Name}WorkflowDefinitions_config_item`
- Module prefix: use the project's established convention — inspect nearby migrations to determine the correct prefix (e.g. `Leave_`, `Pmds_`, `Hcm_`)

**With multiple FK columns** (when the workflow instance references more than one entity — e.g. PartOf + Model):

```csharp
Create.Table("{Prefix}_{WorkflowName}Workflows")
    .WithIdAsGuid()
    .WithFullAuditColumns()
    .WithForeignKeyColumn("PartOfId", "{OwnerTableName}").Nullable()
    .WithForeignKeyColumn("ModelId", "{ModelTableName}").Nullable();
```

Chain additional `.WithForeignKeyColumn(...)` calls for each FK. Mark all nullable unless the relationship is mandatory at creation time.

## (b) Instance with extra columns

When the workflow carries additional state (e.g. cancellation context):

```csharp
Create.Table("{Prefix}_{WorkflowName}Workflows")
    .WithIdAsGuid()
    .WithFullAuditColumns()
    .WithColumn("ApplicationWasRecommended").AsBoolean().WithDefaultValue(false)
    .WithColumn("ApplicationWasApproved").AsBoolean().WithDefaultValue(false)
    .WithColumn("CancellationComments").AsString(4000).Nullable()
    .WithForeignKeyColumn("ModelId", "{ModelTableName}");
```

## (c) Adding columns to existing table

```csharp
[Migration({YYYYMMDDHHmmss})]
public class M{YYYYMMDDHHmmss} : Migration
{
    public override void Up()
    {
        Alter.Table("{Prefix}_{WorkflowName}Workflows")
            .AddColumn("EmployeeNo").AsString(10).Nullable();

        Alter.Table("{Prefix}_{WorkflowName}Workflows")
            .AddColumn("StatusLkp").AsInt64().Nullable();

        Alter.Table("{Prefix}_{WorkflowName}Workflows")
            .AddForeignKeyColumn("SupervisorPositionId", "{Prefix}_Positions").Nullable();
    }

    public override void Down()
    {
        Delete.Column("EmployeeNo").FromTable("{Prefix}_{WorkflowName}Workflows");
        Delete.Column("StatusLkp").FromTable("{Prefix}_{WorkflowName}Workflows");
        Delete.Column("SupervisorPositionId").FromTable("{Prefix}_{WorkflowName}Workflows");
    }
}
```

## (d) Multiple workflow pairs

When creating related workflows together (e.g. application + cancellation):

```csharp
[Migration({YYYYMMDDHHmmss})]
public class M{YYYYMMDDHHmmss} : Migration
{
    public override void Up()
    {
        // --- Application Workflow ---
        Create.Table("{Prefix}_{AppWorkflowName}Workflows")
            .WithIdAsGuid()
            .WithFullAuditColumns()
            .WithForeignKeyColumn("ModelId", "{ModelTableName}");

        Create.Table("{Prefix}_{AppWorkflowName}WorkflowDefinitions")
            .WithIdAsGuid();

        Create.ForeignKey("fk_{Prefix}_{AppWorkflowName}WorkflowDefinitions_config_item")
            .FromTable("{Prefix}_{AppWorkflowName}WorkflowDefinitions")
            .ForeignColumn("Id")
            .ToTable("workflow_definitions").InSchema("workflow")
            .PrimaryColumn("id");

        Create.ForeignKey("fk_{Prefix}_{AppWorkflowName}Workflows_wf_inst")
            .FromTable("{Prefix}_{AppWorkflowName}Workflows")
            .ForeignColumn("Id")
            .ToTable("workflow_instances").InSchema("workflow")
            .PrimaryColumn("id");

        // --- Cancellation Workflow ---
        Create.Table("{Prefix}_{CancelWorkflowName}Workflows")
            .WithIdAsGuid()
            .WithFullAuditColumns()
            .WithColumn("ApplicationWasRecommended").AsBoolean().WithDefaultValue(false)
            .WithColumn("ApplicationWasApproved").AsBoolean().WithDefaultValue(false)
            .WithColumn("CancellationComments").AsString(4000).Nullable()
            .WithForeignKeyColumn("ModelId", "{ModelTableName}");

        Create.Table("{Prefix}_{CancelWorkflowName}WorkflowDefinitions")
            .WithIdAsGuid();

        Create.ForeignKey("fk_{Prefix}_{CancelWorkflowName}WorkflowDefinitions_config_item")
            .FromTable("{Prefix}_{CancelWorkflowName}WorkflowDefinitions")
            .ForeignColumn("Id")
            .ToTable("workflow_definitions").InSchema("workflow")
            .PrimaryColumn("id");

        Create.ForeignKey("fk_{Prefix}_{CancelWorkflowName}Workflows_wf_inst")
            .FromTable("{Prefix}_{CancelWorkflowName}Workflows")
            .ForeignColumn("Id")
            .ToTable("workflow_instances").InSchema("workflow")
            .PrimaryColumn("id");
    }

    public override void Down()
    {
        Delete.Table("{Prefix}_{CancelWorkflowName}WorkflowDefinitions");
        Delete.Table("{Prefix}_{CancelWorkflowName}Workflows");
        Delete.Table("{Prefix}_{AppWorkflowName}WorkflowDefinitions");
        Delete.Table("{Prefix}_{AppWorkflowName}Workflows");
    }
}
```

## (e) OneWayMigration

Use when rollback is impractical:

```csharp
using Shesha.FluentMigrator;

namespace {ModuleNamespace}.Domain.Migrations
{
    [Migration({YYYYMMDDHHmmss})]
    public class M{YYYYMMDDHHmmss} : OneWayMigration
    {
        public override void Up()
        {
            // Schema changes, SQL procedures, etc.
        }
    }
}
```

**With conditional column existence check** (safe to re-run; guards against duplicate additions when migrations may have been applied manually or out of order):

```csharp
[Migration({YYYYMMDDHHmmss})]
public class M{YYYYMMDDHHmmss} : OneWayMigration
{
    public override void Up()
    {
        if (!Schema.Table("{Prefix}_{WorkflowName}Workflows").Column("{FirstColumnId}").Exists())
        {
            Alter.Table("{Prefix}_{WorkflowName}Workflows")
                .AddForeignKeyColumn("{FirstColumnId}", "{FirstRefTable}").Nullable()
                .AddForeignKeyColumn("{SecondColumnId}", "{SecondRefTable}").Nullable();
        }
    }
}
```

Check only the **first** column being added — if it already exists the entire block is skipped. Use this pattern when adding multiple FK columns in a single follow-up migration.

## Column type mapping

| C# Type | FluentMigrator | Notes |
|---------|---------------|-------|
| `Guid` | `.WithIdAsGuid()` | PK |
| `string` | `.AsString(length)` / `.AsStringMax()` | `.Nullable()` for optional |
| `bool` | `.AsBoolean()` | `.WithDefaultValue(false)` |
| `int` | `.AsInt32()` | `.Nullable()` for optional |
| `long` (RefList) | `.AsInt64()` | Column suffixed `Lkp` |
| `decimal` | `.AsDecimal()` | `.Nullable()` for optional |
| `DateTime` | `.AsDateTime()` | `.Nullable()` for optional |
| FK | `.WithForeignKeyColumn("ColId", "Table")` | `.AddForeignKeyColumn()` on Alter |
| Audit | `.WithFullAuditColumns()` | All audit columns |

## Property-to-column mapping

| Domain Property | Migration Column |
|----------------|-----------------|
| `Model` (entity ref) | `ModelId` FK |
| `virtual bool Flag` | `.WithColumn("Flag").AsBoolean()` |
| `virtual string Comments` | `.WithColumn("Comments").AsString(4000)` |
| `[ReferenceList] virtual long? Status` | `.WithColumn("StatusLkp").AsInt64()` |
| `virtual SomeEntity Ref` | `.AddForeignKeyColumn("RefId", "SomeEntity_Table")` |
