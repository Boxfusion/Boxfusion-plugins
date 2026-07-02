---
name: generate-sql-query
description: Generates a safe, read-only Microsoft SQL Server (T-SQL) query from a natural-language request against a Shesha database, using the Shesha entity metadata to find relevant tables, build schema context, and validate the result. Ports the Shesha Automate Engine's SQL generator (prompts + validation rules) so it runs directly in Claude Code without the MCP server. Use when asked to "generate a SQL query", "write SQL from natural language", "query the Shesha database", "generate a view or stored procedure", or similar. Produces only SELECT/INSERT/UPDATE — blocks DELETE/DROP/TRUNCATE/ALTER/CREATE/RENAME.
---

# Generate SQL Query

Turn a natural-language request into a **complete, executable, read-only T-SQL query** for a
Shesha (ABP/NHibernate) SQL Server database. This skill ports the Shesha Automate Engine's
`generate_sql_query` tool: the prompt templates and safety rules are bundled verbatim in
[reference/](reference/); the pipeline below mirrors the engine's `SqlGenerator.process_query`.

The engine used a FAISS vector search to pick relevant tables. Here that step is done with the
LLM table-filter prompt ([reference/filter-tables.md](reference/filter-tables.md)) over the
entity-class list — no embeddings needed.

## Prerequisites

Confirm the connection inputs before starting (see
[reference/data-access.md](reference/data-access.md#connection-inputs)):
- **Shesha backend**: `backend_url` + credentials — to list entity classes, properties, reflists.
- **MSSQL database**: `mssql_server`, `mssql_database` (+ optional user/password) — to read
  column DDL and to execute the candidate query for validation.

If any required input is missing, ask for it and stop — do not guess connection details.

## Pipeline

### Step 1 — Fetch and filter entity classes

Follow [reference/data-access.md](reference/data-access.md#step-a--fetch-entity-classes):
fetch entity classes from the backend and keep only those with both a `tableName` and a
`module`. This filtered list is the table catalog for the next step.

### Step 2 — Find relevant tables (max 5)

Apply [reference/filter-tables.md](reference/filter-tables.md) as the system prompt, with
`{tables}` replaced by the filtered class list (id, className, tableName, description per row)
and the user's request as the user prompt. The result is a JSON array of **≤5 table IDs**.
If it returns an empty array, the request is not database-related — tell the user and stop.

### Step 3 — Build schema context

For the selected table IDs, gather full schema context per
[reference/data-access.md](reference/data-access.md#step-b--class-properties--reference-lists)
and Step C:
- class properties (resolving reference-list options so labels replace magic numbers),
- column DDL from MSSQL,
- assemble into the `{schema_context}` string
  ([format](reference/data-access.md#assembling-schema_context)).

### Step 4 — Validate schema sufficiency (loop, max 3)

Apply [reference/validate-schema.md](reference/validate-schema.md) with `{schema_context}` and
`{user_query}` filled in. Read back three fields:
- `expand_schema` (bool) — is more schema needed?
- `request_more_schema` (string) — a natural-language query naming missing className/tableName.
- `relevant_tables` (string[]) — IDs of all relevant tables.

While `expand_schema` is true and fewer than 3 iterations have run: use `request_more_schema`
to select more tables (re-run Step 2's filter over the class list with that query), merge any
new IDs into the relevant set, rebuild `schema_context`, and re-validate. Accumulate
`relevant_tables` across iterations (deduplicate). Stop when `expand_schema` is false or after
3 iterations.

Then rebuild `schema_context` one final time from the full accumulated relevant-table set.

### Step 5 — Generate SQL (loop, max 3)

Apply [reference/sql-query.md](reference/sql-query.md) as the system prompt (with the final
`{schema_context}`) and the user's request as the user prompt. For each attempt:

1. If the response contains `"I don't know"` or `"I cannot"`, treat it as a refusal — stop and
   ask the user to refine the request. Do not output SQL.
2. Run the safety validation in [reference/validation-rules.md](reference/validation-rules.md)
   (extract from markdown → block dangerous commands / multiple statements / comments). On
   failure, append the failure reason to the generation prompt as a correction hint and retry.
3. Clean up the SQL and **execute it** against the MSSQL database to confirm it runs. On a SQL
   error, append the error text to the generation prompt as a hint and retry.
4. On success, stop.

Give up after 3 failed correction attempts and report the collected errors.

### Step 6 — Return

Return only the validated SQL query — no explanation or commentary, matching the template's
"Return ONLY the SQL query" guideline. If generation failed, ask the user to be more explicit;
do not invent SQL.

## Safety guarantees (non-negotiable)

Enforced by [reference/validation-rules.md](reference/validation-rules.md):
- **Blocked**: `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `RENAME`; multiple statements
  (>1 `;`); SQL comments (`--`, `/*`).
- **Allowed**: `SELECT`, `INSERT`, `UPDATE`. Physical deletes are never generated — use the
  `[IsDeleted]` soft-delete column (`0` = active, `1` = deleted).
- Never alter the schema; never invent columns/properties; respect Shesha audit columns and
  `Frwk_Discriminator` values.

## Bundled resources

- [reference/filter-tables.md](reference/filter-tables.md) — verbatim table-filter prompt.
- [reference/validate-schema.md](reference/validate-schema.md) — verbatim schema-sufficiency prompt.
- [reference/sql-query.md](reference/sql-query.md) — verbatim SQL-generation prompt.
- [reference/validation-rules.md](reference/validation-rules.md) — verbatim safety/extraction/cleanup rules.
- [reference/data-access.md](reference/data-access.md) — backend endpoints + MSSQL schema gathering.
