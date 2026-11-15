# Shesha Authorization and Access Control Guide

**Concepts and models in this guide are general Shesha documentation — the concrete API calls
shown in its code samples (`ICurrentUser.HasPermissionAsync`, `GetPermissionScope`,
`IsPermissionScopedToEntity`, async `BuildExpressionAsync`) are illustrative, not a guaranteed
contract for every Shesha version. They are known to be **absent** from `Shesha.Framework` 0.43.37
(confirmed by reflection against the package), where the real, working shapes are different — see
[implementation-patterns.md](implementation-patterns.md)'s top-of-file note and its "verified-real
pattern" for `ShaSpecification`. Verify against the target project's actual referenced package
version before writing real code from this guide's examples (see SKILL.md § Key Rules, "Verify the
framework API shape") — the concepts (RBAC/Resource-Based/ABAC, naming conventions, the decision
tree) remain valid regardless of the exact method names in a given version.

## Core Concepts

Shesha's access control framework is built around these key concepts:

- **Users** – Individual accounts representing system actors (people or integrations).
- **Persons** – `Person` is a standard entity provided out-of-box. Each `User` is associated with a `Person` entity providing additional information (name, contact details, etc.). A `Person` can exist independently of a `User` (e.g., clients who don't need login access).
- **Roles** – Named sets of permissions defining what a user can do.
- **Entity-scoped roles** – Roles assigned in the context of a specific entity instance (e.g., "Account Manager" scoped to a particular account).
- **Permissions** – Granular controls over specific features or actions.
- **Role Type** – Defines the scope and context in which roles are applicable.

## Shesha's Hybrid Access Control Model

Shesha implements a hybrid model combining three authorization approaches:

1. **Role-Based Access Control (RBAC)** – Global permissions through role assignments
2. **Resource-Based Authorization** – Instance-level permissions on specific entities
3. **Attribute-Based Access Control (ABAC)** – Dynamic permissions based on conditions

---

## 1. Role-Based Access Control (RBAC)

### When to Use

- Permissions apply globally across all entities of a type
- Organizational structure is relatively stable
- You need simple, easy-to-understand access control
- Most users in a role should have the same permissions

**Example**: All Administrators can view all users in the system.

### Standard Roles

| Role | Description | Permissions |
|------|-------------|-------------|
| **User** | Standard application features | Person-View/Create/Update/Delete, Account-View/Create/Update/Delete, Organisation-View/Create/Update/Delete, User-View-if-CurrentUser, User-Manage-if-CurrentUser |
| **Administrator** | Administrative functions | User-View/Create/Update/Delete/ResetPassword/Suspend, RefList-View/Create/Update/Delete, LogOnAudit-View, Notification-ViewAudit, DataAudit-View |
| **Configurator** | Configuration Studio access | Configuration-Manage |

### Permission Naming Convention (RBAC)

**Format:** `{Entity}-{Action}`

Examples: `User-View`, `User-Create`, `User-Update`, `User-Delete`, `User-ResetPassword`, `User-Suspend`

### Permission Granularity

Combine actions when they are always assigned together:
- `User-View` + `User-Manage` (instead of separate Create/Update/Delete/ResetPassword/Suspend)

Only separate permissions when specific rights need to be assigned independently.

---

## 2. Resource-Based Authorization (Instance-Level)

### When to Use

- Users should only access specific instances of an entity type
- Access is determined by organizational structure (regions, departments, accounts)
- You need to delegate management of specific resources
- Permissions follow hierarchical relationships between entities

**Example**: Account Manager role scoped to Account #123 allows managing only that account.

### How It Works

Set a Role's `RoleType` property to the relevant entity type. Default role types:
- **Standard Role** (unscoped) — for global roles
- **Organization Specific** — scoped to organizations
- **Account Specific** — scoped to accounts
- Custom types as needed (e.g., Region Specific, Project Specific)

### Permission Naming Convention (Resource-Based)

**Format:** `{Entity}-{Action}-where-Scoped[-to-{ScopeEntity}]`

#### Direct Scoping (role scoped directly to the protected entity)

| Permission | Protected Entity | Scoping Entity |
|-----------|-----------------|----------------|
| `Account-View-where-Scoped` | Account | Account |
| `Account-Update-where-Scoped` | Account | Account |

#### Hierarchical Scoping (role scoped to a parent/ancestor entity)

| Permission | Protected Entity | Scoping Entity |
|-----------|-----------------|----------------|
| `Account-View-where-Scoped-to-Region` | Account | Region |
| `Account-Update-where-Scoped-to-Region` | Account | Region |
| `Account-View-where-Scoped-to-Country` | Account | Country |

### Key Difference from RBAC

```
RBAC:
User → Role → Global Permission
John → Administrator → Account-View
Result: John can view ALL accounts

Resource-Based:
User → Entity-Scoped Role → Resource Permission
John → Account Manager (scoped to Account #123) → Account-View-where-Scoped
Result: John can view ONLY Account #123
```

---

## 3. Attribute-Based Access Control (ABAC)

### When to Use

- Access depends on dynamic relationships between user and resource
- Conditions must be evaluated at runtime
- You need highly flexible, context-aware permissions
- Explicitly assigning access to every resource instance is impractical

**Example**: A Support Agent can view any ticket assigned to them without explicit role assignments per ticket.

### How It Works

ABAC checks attributes of:
- **User** (role, department, clearance level)
- **Resource** (owner, status, assigned agent, classification)
- **Environment** (time, location, device)
- **Action** (view, edit, delete)

### Permission Naming Convention (ABAC)

**Format:** `{Entity}-{Action}-if-{Condition}`

Examples:
- `Ticket-View-if-Assigned` — view tickets IF user is the assigned agent
- `Document-Edit-if-Owner` — edit documents IF user is the document owner
- `User-Manage-if-CurrentUser` — manage user profile IF it's their own
- `Report-View-if-SameDepartment` — view reports IF same department

### Key Difference from Resource-Based

```
Resource-Based:
John → Explicitly assigned to WorkOrder #456
Must be assigned to each work order individually

ABAC:
John → Has WorkOrder-Complete-if-Assigned permission
Condition: workOrder.assignedTo == currentUser
Automatically applies to ALL matching work orders
```

---

## When to Use Each Model

| Scenario | Model | Example |
|----------|-------|---------|
| Administrative functions for all users | RBAC | Administrator can view all user accounts |
| Regional manager oversees accounts in their region | Resource-Based | Regional Manager scoped to "Western Region" |
| User can edit their own profile only | ABAC | User-Manage-if-CurrentUser |
| Sales rep manages specifically assigned accounts | Resource-Based | Account Manager scoped to Account #123, #456 |
| Support agent handles tickets assigned to them | ABAC | Ticket-View-if-Assigned |
| Department head sees all documents in their department | ABAC | Document-View-if-SameDepartment |
| Country manager oversees regional operations | Resource-Based (hierarchical) | Country Manager scoped to "South Africa" |

### Decision Tree

1. Does permission apply to ALL instances globally? → **RBAC**
2. Is access based on organizational structure/specific assignments? → **Resource-Based**
3. Is access based on dynamic relationships/conditions? → **ABAC**
4. Multiple approaches needed? → **Combine** (check: RBAC → Resource-Based → ABAC)
5. Is this a child entity?
   - Supporting detail with no independent authorization? → **Inherit from parent + MUST have specification**
   - Independent authorization requirements? → **Consider child-specific permissions + MUST have specification**

---

## API-Level Access Control

### Simple: AbpAuthorize Attribute

```csharp
[AbpAuthorize("WorkOrder-View")]
[HttpPost, Route("[action]")]
public async Task<WorkOrderDto> GetWorkOrder(Guid id)
{
    var workOrder = await _workOrderRepo.GetAsync(id);
    return ObjectMapper.Map<WorkOrderDto>(workOrder);
}
```

### Complex: Custom Authorization Logic

For hybrid models, implement custom authorization checking RBAC → Resource-Based → ABAC in order:

```csharp
[HttpPost, Route("[action]")]
public async Task<CompleteWorkOrderResponse> CompleteWorkOrder(CompleteWorkOrderRequest input)
{
    var workOrder = await _workOrderRepo.GetAsync(input.WorkOrderId);

    if (!await UserHasPermission_WorkOrder_Complete(workOrder))
        throw new AbpAuthorizationException("User does not have permission to complete the work order.");

    // Business logic...
}

private async Task<bool> UserHasPermission_WorkOrder_Complete(WorkOrder workOrder)
{
    // 1. RBAC: Global permission (fastest)
    if (await _currentUser.HasPermissionAsync("WorkOrder-Complete"))
        return true;

    // 2. Resource-Based: Scoped to region
    if (workOrder.Region != null
        && _currentUser.IsPermissionScopedToEntity("WorkOrder-Complete-where-Scoped-to-Region", workOrder.Region.Id))
        return true;

    // 3. ABAC: Condition-based (slowest)
    if (await _currentUser.HasPermissionAsync("WorkOrder-Complete-if-Assigned")
        && workOrder.AssignedTo != null
        && workOrder.AssignedTo.Id == _currentUser.Person?.Id)
        return true;

    return false;
}
```

---

## Data-Level Access Control (Global Specifications)

Global specifications are **MANDATORY** for all entities to prevent information leakage. They automatically filter all queries based on user permissions.

### Example: Combining All Three Models

```csharp
[Description("Specification to limit visibility of Accounts based on permissions.")]
[GlobalSpecification]
public class AccountPermissionsSpecification : ShaSpecification<Account>
{
    private readonly ICurrentUser _currentUser;

    public AccountPermissionsSpecification(ICurrentUser currentUser)
    {
        _currentUser = currentUser;
    }

    public override async Task<Expression<Func<Account, bool>>> BuildExpressionAsync()
    {
        if (_currentUser.Person == null) return account => false;

        // 1. RBAC: Global permission
        if (await _currentUser.HasPermissionAsync("Account-View"))
            return account => true;

        // 2. Resource-Based: Entity-scoped permissions
        var scopedAccounts = _currentUser.GetPermissionScope("Account-View-where-Scoped");
        var scopedRegions = _currentUser.GetPermissionScope("Account-View-where-Scoped-to-Region");
        var scopedCountries = _currentUser.GetPermissionScope("Account-View-where-Scoped-to-Country");

        // 3. ABAC: Condition-based permissions
        var canViewIfOwner = await _currentUser.HasPermissionAsync("Account-View-if-Owner");
        var canViewIfSameDepartment = await _currentUser.HasPermissionAsync("Account-View-if-SameDepartment");

        var currentPersonId = _currentUser.Person.Id;
        var currentDepartmentId = _currentUser.Person.Department?.Id;

        // 4. Build combined expression
        return account =>
            // Resource-Based checks
            scopedAccounts.Contains(account.Id)
            || (account.Region != null && scopedRegions.Contains(account.Region.Id))
            || (account.Region != null && account.Region.Country != null
                && scopedCountries.Contains(account.Region.Country.Id))
            // ABAC checks
            || (canViewIfOwner && account.Owner != null
                && account.Owner.Id == currentPersonId)
            || (canViewIfSameDepartment && account.Department != null
                && account.Department.Id == currentDepartmentId);
    }
}
```

### Critical Rules for Global Specifications

1. Always check `_currentUser.Person == null` first → return `entity => false`
2. Return `entity => true` for global RBAC permissions (performance optimization)
3. Build efficient expressions that minimize database queries
4. Use `Contains()` for checking scoped entity IDs
5. Handle null navigation properties properly
6. Collect all scoped IDs and boolean flags BEFORE the return expression

---

## Child Entity Security

### The Problem: Information Leakage

If a parent entity is secured but child entities lack specifications, users can query child entities directly and bypass parent security.

### The Solution: Two-Layer Security Model

**Layer 1: Global Specifications** — Automatic data filtering for ALL queries
**Layer 2: Permission Checks** — Explicit checks on CREATE/UPDATE/DELETE operations

### Default Rule: Inherit Parent Permissions

Most child entities should use parent permissions:

```csharp
// CORRECT: Use parent permissions for supporting child entities
permissions.Add("Order-View");    // Controls viewing orders AND their line items
permissions.Add("Order-Update");  // Controls updating orders AND managing their line items

// WRONG: Separate permissions for supporting child entities
permissions.Add("OrderLine-View");  // Unnecessary permission sprawl
```

### Child Entity Specification (Inheriting Parent Permissions)

```csharp
[GlobalSpecification]
[Description("Filters order lines based on user's Order permissions")]
public class OrderLinePermissionsSpecification : ShaSpecification<OrderLine>
{
    private readonly ICurrentUser _currentUser;

    public OrderLinePermissionsSpecification(ICurrentUser currentUser)
    {
        _currentUser = currentUser;
    }

    public override async Task<Expression<Func<OrderLine, bool>>> BuildExpressionAsync()
    {
        if (_currentUser.Person == null)
            return line => false;

        // Check parent (Order) permissions
        if (await _currentUser.HasPermissionAsync("Order-View"))
            return line => true;

        var scopedOrders = _currentUser.GetPermissionScope("Order-View-where-Scoped");
        var scopedCustomers = _currentUser.GetPermissionScope("Order-View-where-Scoped-to-Customer");

        return line =>
            line.Order != null && (
                scopedOrders.Contains(line.Order.Id) ||
                (line.Order.Customer != null && scopedCustomers.Contains(line.Order.Customer.Id))
            );
    }
}
```

### When Child Entity Permissions ARE Valid

Only create child-specific permissions when:
- Child has **independent business operations** (e.g., line-level approval)
- Child has **different security classifications** (e.g., document confidentiality levels)
- Child is **reusable across multiple parents** (e.g., attachments with type-based sensitivity)
- Child has **complex lifecycle/workflow** with distinct roles at each stage
- Child forms its **own authorization boundary** (e.g., hospital beds)

### Decision Framework

> "Does this child entity have authorization concerns that are INDEPENDENT of its parent's authorization?"

**Use parent permissions when** the child is:
- A supporting detail (Address, ContactDetail, Comment)
- Purely compositional — cannot exist without parent
- Has no independent business logic requiring separate authorization
- Is a log/audit record

**Use child permissions when** the child has:
- Independent business operations
- Different security classifications
- Own lifecycle/workflow
- Cross-cutting concerns
- Separate regulatory requirements
- Distinct operational roles

---

## Permission Naming Convention Summary

| Model | Convention | Examples |
|-------|-----------|----------|
| **RBAC** | `{Entity}-{Action}` | `Account-View`, `User-Manage`, `WorkOrder-Complete` |
| **Resource-Based** | `{Entity}-{Action}-where-Scoped[-to-{ScopeEntity}]` | `Account-View-where-Scoped`, `Account-Update-where-Scoped-to-Region` |
| **ABAC** | `{Entity}-{Action}-if-{Condition}` | `Ticket-View-if-Assigned`, `Document-Edit-if-Owner` |

---

## Best Practices

1. Start with RBAC for baseline permissions, add Resource-Based and ABAC only where needed
2. Use consistent naming conventions
3. ALWAYS implement global specifications for ALL entities
4. Simplify the permission list — avoid redundancy
5. Do NOT create duplicate permissions for global roles
6. Check permissions in order: RBAC → Resource-Based → ABAC
7. Default to parent permissions for child entities
8. Always add specifications regardless of permission approach
9. Test for information leakage
10. Document exceptions when child entities need their own permissions

### Understanding Permission Hierarchies

When designing Resource-Based permissions with hierarchical scoping (e.g., Country → Region → Account):
- **Multiple levels**: Create permission variants for each level users may be assigned at
- **Single level**: Only need permissions for that one level

### Avoid Redundancy Checklist

- No `System-View-All-Accounts` when `Account-View` exists
- No scoped variants when global permissions suffice
- Combine Create/Update/Delete into `Manage` when always assigned together
- No separate child entity permissions when parent permissions suffice
