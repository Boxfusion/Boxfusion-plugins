# SQL Safety Validation & Cleanup

Ported verbatim from the engine's `SQLValidator` (`agent_services/sql_generator/helpers.py`).
Every candidate SQL from the generation step MUST pass these checks before it is executed
or returned. If a check fails, feed the failure reason back into the SQL-generation prompt
and regenerate (up to the retry limit).

## 1. Extract SQL from markdown

The model may wrap SQL in a fenced code block. Extract the raw SQL:

1. If the string starts with ` ``` ` and ends with ` ``` `, strip the three backticks from
   each end. If the remaining text contains a newline and does not start with one, drop the
   first line (this removes a language specifier like `sql`).
2. Otherwise try, in order:
   - block pattern ` ```sql\n(.*?)``` ` (dot matches newline) → use capture group 1
   - inline pattern `` `(.*?)` `` (dot matches newline) → use capture group 1
3. If nothing matched, strip any leading/trailing backticks (`` ` ``) from the string.

Then trim whitespace and remove a single trailing `;` before running the safety check.

## 2. Safety check (`_is_sql_safe`)

Lowercase the extracted SQL, then reject if ANY of these hold:

- **Dangerous commands** — the lowercased SQL contains any of these substrings
  (note the trailing space in each): `"delete "`, `"drop "`, `"truncate "`, `"alter "`,
  `"create "`, `"rename "`. Reason: `Contains dangerous command: <cmd>`.
- **Multiple statements** — more than one `;` present. Reason:
  `Multiple statements detected (<n> semicolons)`.
- **SQL comments** — the SQL contains `--` or `/*`. Reason: `SQL comments detected`.

Otherwise the SQL is considered safe (`SQL appears safe`).

> Note (faithful to the engine): the safety check blocks `DELETE/DROP/TRUNCATE/ALTER/CREATE/RENAME`
> but does NOT block `INSERT` or `UPDATE`. The prompt template (`sql-query.md`) instructs the
> model that only retrieve/insert/update are permitted and to use the `[IsDeleted]` soft-delete
> column instead of physical deletes. Keep both layers — the prompt guidance and this validator.

## 3. Model refusal check

Before validation, if the model's raw response contains `"I don't know"` or `"I cannot"`,
treat it as a refusal — do not attempt to run it. Return a message asking the user to refine
the query. Do not generate any SQL.

## 4. Cleanup before execution (`sql_cleanup`)

Produce the final executable string:

1. Trim whitespace.
2. If it starts with ` ``` `, strip leading backticks; if what remains starts with `sql`
   (case-insensitive), drop those 3 characters and trim; if it ends with ` ``` `, strip the
   trailing fence and trim.

## 5. Execute to confirm (optional but faithful)

The engine executes the cleaned SQL against the target MSSQL database to confirm it runs.
If execution returns an error, feed the error text back into the generation prompt as a
correction hint and regenerate. Only queries that pass validation AND execute successfully
are returned.
