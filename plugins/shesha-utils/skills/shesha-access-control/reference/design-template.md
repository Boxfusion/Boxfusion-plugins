# Access Control Design Document Template

Use this template when creating access control design documents for Shesha applications.

---

```markdown
# {Application Name} Access Control Design

## Executive Summary

{Brief description of the access control model, key decisions, and scope.}

## Domain Model Overview

### Entity Hierarchy

{Show the entity hierarchy with parent-child relationships:}

```
{TopLevelEntity} (Top-level)
├── {ChildEntity1}
│   ├── {GrandchildEntity1}
│   └── {GrandchildEntity2}
├── {ChildEntity2}
│   └── {GrandchildEntity3}
└── {ChildEntity3}
```

### Key Relationships

{Document important relationships that affect access control decisions.}

## Access Control Requirements

### Business Requirements

{List numbered business requirements, e.g.:}
1. Multi-level security: {levels and their meaning}
2. Data isolation: {what data must be isolated}
3. Role separation: {roles that must not overlap}

### Technical Requirements

1. Performance: Permission checks must not degrade system performance
2. Scalability: Support {expected scale}
3. Zero Trust: Default to no access unless explicitly granted

## Role Definitions

### {Level} Level Roles

#### {Role Name}
**Scope**: {Global (unscoped) / {Entity}-specific}
**Purpose**: {One-line purpose}
**Key Responsibilities**:
- {Responsibility 1}
- {Responsibility 2}
- {Responsibility 3}

{Repeat for each role...}

## Permissions Catalog

### Naming Conventions

- **RBAC**: `{Entity}-{Action}`
- **Resource-Based**: `{Entity}-{Action}-where-Scoped[-to-{ScopeEntity}]`
- **ABAC**: `{Entity}-{Action}-if-{Condition}`

### {Entity Group} Permissions

| Permission | Type | Description |
|------------|------|-------------|
| `{Entity}-View` | RBAC | View all {entities} globally |
| `{Entity}-Create` | RBAC | Create {entities} |
| `{Entity}-Update` | RBAC | Update any {entity} |
| `{Entity}-Delete` | RBAC | Delete any {entity} |
| `{Entity}-View-where-Scoped` | Resource-Based | View specific assigned {entities} |
| `{Entity}-View-where-Scoped-to-{Parent}` | Resource-Based | View {entities} in assigned {parents} |
| `{Entity}-View-if-Owner` | ABAC | View {entities} where user is owner |

{Repeat for each entity group...}

## Role-Permission Matrix

### {Level} Roles

| Permission | {Role1} | {Role2} | {Role3} |
|------------|:-------:|:-------:|:-------:|
| **{Entity} Management** |
| {Entity}-View | ✓ | ✓ | ✓ |
| {Entity}-Create | ✓ | - | - |
| {Entity}-Update | ✓ | - | - |
| {Entity}-Delete | ✓ | - | - |

{Repeat for each level...}

## Entity-Action Authorization Matrix

| Entity | Action | Auth Model | Permissions Used | Notes |
|--------|--------|-----------|-----------------|-------|
| {Entity} | View | Hybrid | {Entity}-View, {Entity}-View-where-Scoped, {Entity}-View-if-Owner | RBAC checked first |
| {Entity} | Create | RBAC + Resource | {Entity}-Create, {Entity}-Create-where-Scoped-to-{Parent} | Requires parent context |
| {Entity} | Update | Hybrid | {Entity}-Update, {Entity}-Update-where-Scoped | |
| {Entity} | Delete | RBAC | {Entity}-Delete | Admin only |

## Child Entity Security

| Child Entity | Parent Entity | Permission Approach | Justification |
|-------------|--------------|-------------------|---------------|
| {Child1} | {Parent1} | Inherit parent | Supporting detail, no independent auth |
| {Child2} | {Parent2} | Child-specific | Has independent workflow/classification |

## Implementation Guidance

### Authorization Architecture

{Describe the authorizer pattern to use, list authorizer interfaces needed.}

### Global Specifications Required

| Entity | Specification Class | Inherits From |
|--------|-------------------|---------------|
| {Entity1} | {Entity1}PermissionsSpecification | Own permissions |
| {ChildEntity1} | {ChildEntity1}PermissionsSpecification | {Entity1} permissions |

### Role Type Configuration

| Role Type | Scoping Entity | Used By Roles |
|-----------|---------------|---------------|
| Standard Role (unscoped) | N/A | {list roles} |
| {Entity}-Specific | {Entity} | {list roles} |

## Security Considerations

1. **Default Deny**: All access denied by default
2. **Separation of Concerns**: {describe any isolation requirements}
3. **Audit Trail**: {list operations requiring audit}

## Design Decisions & Justifications

| Decision | Rationale |
|----------|-----------|
| {Decision 1} | {Why this approach was chosen} |
| {Decision 2} | {Why this approach was chosen} |

## Testing Strategy

### Permission Test Scenarios

{List key test scenarios for each role/permission combination.}

### Information Leakage Tests

{List tests to verify child entity security.}
```
