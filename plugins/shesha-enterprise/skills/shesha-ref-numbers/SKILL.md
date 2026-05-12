---
name: shesha-ref-numbers
description: Generates reference number logic for business entities in Shesha framework .NET applications. Creates sequential reference number generator usage code, format strings with date/sequence/financial-year placeholders, reset cycle configuration, and custom generator classes implementing IRefNumberGenerator. Use when the user asks to create, scaffold, implement, add, or generate reference numbers, sequence numbers, auto-numbering, order numbers, invoice numbers, case numbers, ticket numbers, or any auto-incrementing identifiers for business entities in a Shesha project.
---

# Shesha Reference Number Generation

Generate reference number code for a Shesha/.NET/ABP application based on $ARGUMENTS.

## Instructions

- Use `SequentialRefNumberGenerator` for the vast majority of cases — it handles counting, formatting, and resetting automatically.
- Each `SequenceName` gets its own independent counter in the database. Choose descriptive, unique names.
- Prefer **compound format strings** that include dates for readability (e.g. `"ORD-{0:yyyy}-{1:0000}"` over `"ORD-{1:0000}"`).
- The generator is **thread-safe** — multiple concurrent calls are guaranteed unique numbers.
- Counters are **database-backed** and survive application restarts.
- If the user mentions financial year formats, use `{FY}`, `{FY-1}`, `{FYYYY}`, `{FYYYY-1}` placeholders and confirm the financial year start month.
- Only create a custom generator (implementing `IRefNumberGenerator`) if sequential numbering genuinely doesn't fit the requirement.

## Artifact catalog

| # | Artifact | Layer | Template |
|---|----------|-------|----------|
| 1 | Sequential Ref Number Usage | Application | [sequential-generator.md](sequential-generator.md) §1 |
| 2 | Generator Manager Usage | Application | [sequential-generator.md](sequential-generator.md) §2 |
| 3 | Custom Generator Class | Application | [custom-generator.md](custom-generator.md) §1 |

## Quick reference

### Format string placeholders

| Placeholder | Output | Description |
|-------------|--------|-------------|
| `{0:yyyy}` | `2026` | Full year |
| `{0:yy}` | `26` | Two-digit year |
| `{0:MM}` | `03` | Month (zero-padded) |
| `{0:dd}` | `07` | Day (zero-padded) |
| `{0:yyyy-MM-dd}` | `2026-03-07` | Full date |
| `{1}` | `42` | Plain sequence number |
| `{1:0000}` | `0042` | Padded to 4 digits |
| `{1:00000}` | `00042` | Padded to 5 digits |
| `{FY}` | `26` | Two-digit financial year |
| `{FY-1}` | `25` | Two-digit previous financial year |
| `{FYYYY}` | `2026` | Four-digit financial year |
| `{FYYYY-1}` | `2025` | Four-digit previous financial year |

### Reset cycles

| Cycle | Resets when | Extra settings needed |
|-------|-----------|----------------------|
| `Never` | Never resets | None |
| `Everyday` | Start of each day | None |
| `EveryWeek` | Specific day each week | `ResetDay` |
| `EveryMonth` | Specific day each month | `ResetDayOfMonth` |
| `EveryYear` | Specific date each year | `ResetMonth` + `ResetDayOfMonth` |

### Key types

| Type | Namespace / Location |
|------|---------------------|
| `SequentialRefNumberGenerator` | `Shesha.Workflow.RefNumberGenerator` |
| `SequentialRefNumberGeneratorSettings` | `Shesha.Workflow.RefNumberGenerator` |
| `IRefNumberGenerator` | `Shesha.Enterprise.Domain.Service.RefNumberGenerator` |
| `IRefNumberGeneratorManager` | `Shesha.Workflow.RefNumberGenerator` |
| `RefListSequenceResetCycle` | `Shesha.Enterprise.Domain.Service.RefNumberGenerator` |
| `RefListResetDay` | `Shesha.Enterprise.Domain.Service.RefNumberGenerator` |
| `RefListResetMonth` | `Shesha.Enterprise.Domain.Service.RefNumberGenerator` |

### Common examples at a glance

| Pattern | Format | Output |
|---------|--------|--------|
| Simple order | `"ORD-{1:0000}"` | `ORD-0001` |
| Yearly invoice | `"INV-{0:yyyy}-{1:0000}"` | `INV-2026-0001` |
| Financial year case | `"CASE-{FY-1}/{FY}-{1:00000}"` | `CASE-25/26-00001` |
| Daily ticket | `"TKT-{0:yyyy-MM-dd}-{1:000}"` | `TKT-2026-03-07-001` |
| Monthly receipt | `"RCT-{0:yyyyMM}-{1:0000}"` | `RCT-202603-0001` |
| Custom start | `"ACC-{1}"` (Starting=1000) | `ACC-1000` |

### Workflow integration

Reference numbers can be auto-assigned to workflow instances via **Process Settings** in the Workflow Designer — select a generator and configure its parameters. No code needed when using workflow integration.

Now generate the requested artifact(s) based on: $ARGUMENTS
