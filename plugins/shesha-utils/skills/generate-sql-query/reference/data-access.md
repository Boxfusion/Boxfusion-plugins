# Data Access — Gathering Schema Context

How to collect the two inputs the templates need: the **table list** (for `filter-tables.md`)
and the **schema context** (for `validate-schema.md` and `sql-query.md`). Ported from the
engine's `SqlGenerator`, `BackendAPI`, and `SqlDatabase`.

## Table of contents
- [Connection inputs](#connection-inputs)
- [Step A — Fetch entity classes (Shesha backend)](#step-a--fetch-entity-classes)
- [Step B — Class properties & reference lists](#step-b--class-properties--reference-lists)
- [Step C — Column DDL (MSSQL)](#step-c--column-ddl-mssql)
- [Assembling schema_context](#assembling-schema_context)

## Connection inputs

Two connections are required (the engine reads these from MCP request headers; for the skill,
ask the user or read them from the project config):

- **Shesha backend** — `backend_url`, `backend_user_name`, `backend_password`,
  `backend_secret_key`. Used to list entity classes, properties, and reference lists.
- **MSSQL database** — `mssql_server`, `mssql_database`, and optionally `mssql_username` +
  `mssql_password` (Windows/integrated auth if omitted). Used to read column DDL and to
  execute the candidate query for validation.

`mssql_username`/`mssql_password` are optional; every other field is required.

Authenticate to the backend by POSTing credentials to obtain a bearer token, then send
`Authorization: Bearer <token>` on every backend call.

## Step A — Fetch entity classes

`GET {backend_url}/api/services/app/EntityConfig/GetMainDataList`
params: `maxResultCount=10000`, `sorting=className`.

From `items`, keep only entries where `notImplemented` is falsy AND `suppress` is falsy, and
project these fields: `id`, `className`, `tableName`, `module`, `description`,
`discriminatorValue`, `name`.

**Filter (matches `PrivateUtil.filter_classes`)**: keep only classes that have BOTH a
non-empty `tableName` and a non-empty `module`. This filtered set is the `{tables}` input for
`filter-tables.md` — pass id, className, tableName, description per row.

## Step B — Class properties & reference lists

For each relevant class id:

`GET {backend_url}/api/ModelConfigurations/{class_id}` → read `properties`; project each to
`name`, `label`, `description`, `dataType`, `referenceListName`, `referenceListModule`.

For any property with `dataType == "reference-list-item"` that has both `referenceListName`
and `referenceListModule`, resolve its options so the query can show labels instead of magic
numbers (guideline 11 in `sql-query.md`):

1. Find the module id: `GET {backend_url}/api/services/app/Module/GetAll` filtered by
   `Name == referenceListModule`.
2. Find the reference list id: `GET {backend_url}/api/services/app/Entities/GetAll` with
   `entityType=Shesha.Framework.ReferenceList`, filtered by `isLast == true` and
   `module == <moduleId>`, `querySearch=<referenceListName>`.
3. Fetch items: `GET {backend_url}/api/services/app/Entities/GetAll` with
   `entityType=Shesha.Framework.ReferenceListItem`,
   `properties=item itemValue color icon shortAlias description ... orderIndex id`,
   filtered by `ReferenceList == <reflistId>`.

Attach the returned items as the property's `options` (each has `item` = label,
`itemValue` = numeric value).

## Step C — Column DDL (MSSQL)

For each relevant table, read its column schema from the target database. Query
`INFORMATION_SCHEMA` (columns, primary keys, foreign keys, indexes) for
`[dbo].[<tableName>]`, or use any available DB tool/MCP. This produces the DDL string used as
each class's `schema` in the context.

When a table's DDL is available, drop non-reference-list properties from that class (the DDL
already describes ordinary columns); keep only `reference-list-item` properties so their
option maps still reach the prompt.

## Assembling schema_context

Build the `{schema_context}` string per class (matches `PrivateUtil.schema_with_properties`):

```
ID: <id>
Class: <className>
Table Name: <tableName>
Description: <description or "No description available">
Schema: <DDL or "No schema available">
Reflist Options: <reflistOptions or "No reflist options available">
Reference List: <propName> (<referenceListName>) - Options: <json options>   # per reflist prop
Properties:
- <propName> (<dataType>)                                                     # per property
```

Concatenate all class blocks (blank line between) into the final `schema_context`.
