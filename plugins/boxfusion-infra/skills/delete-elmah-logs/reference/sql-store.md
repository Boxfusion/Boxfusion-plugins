# Elmah in the database (Shesha.Elmah)

Shesha.Elmah writes errors to the app's `Default` connection string. It uses `SheshaSqlErrorLog` for SQL Server or `SheshaPgsqlErrorLog` for PostgreSQL, picked by the `DbmsType` config value (default `SQLServer`).

## Contents
- Schema
- Getting a connection
- SQL Server
- PostgreSQL

## Schema

| Object | Notes |
|---|---|
| `elmah.errors` | One row per error. `all_xml` holds the full payload and makes up almost all of the size. A heap with a nonclustered PK on `error_id`. |
| `elmah.error_refs` | Links errors to entities (`error_id`, `ref_type`, `ref_id`). **No foreign key** to `errors`, and no index on `error_id`. |
| `elmah.vw_referenced_errors` | A view that inner-joins the two tables. Orphaned refs drop out of it on their own. |

The only index useful for time filters is `ix_errors_app_time_seq (application, time_utc DESC, sequence DESC)`. Filter on `application` **and** `time_utc` so each batch seeks instead of scanning the heap.

## Getting a connection

- Find the connection string in this order: App Service **Connection strings** `Default`, then the app setting `ConnectionStrings__Default`, then `appsettings*.json` (`ConnectionStrings:Default`). Also read `DbmsType`.
  ```bash
  az webapp config connection-string list --subscription "$SUB" -g "$RG" -n "$APP" --query "[?name=='Default'].{type:type}" -o table
  az webapp config appsettings list --subscription "$SUB" -g "$RG" -n "$APP" --query "[?name=='DbmsType' || name=='ConnectionStrings__Default'].name" -o tsv
  ```
- Never echo the full connection string or password into the chat. Pass it to `sqlcmd`/`psql` through an environment variable.
- Azure SQL and Azure PostgreSQL firewalls usually block a developer IP (Boxfusion's `auto-sql-shared-prod` only allows Azure services). Prefer `kudu-elmah.sh sql-start`, which runs `scripts/elmah-sql.js` (Linux) or `scripts/elmah-sql.ps1` (Windows) inside the app's Kudu with the app's own connection string, so neither the firewall nor the secret is touched. Only for running statements by hand: ask the user to add a temporary firewall rule. Do not add one silently.

## SQL Server

**1. Size it up (read-only):**
```sql
SELECT application, COUNT(*) AS rows, MIN(time_utc) AS oldest, MAX(time_utc) AS newest
FROM elmah.errors GROUP BY application;

SELECT COUNT(*) AS refs FROM elmah.error_refs;

EXEC sp_spaceused 'elmah.errors';
```

**2a. Delete everything (fastest, minimal logging):**
```sql
TRUNCATE TABLE elmah.error_refs;
TRUNCATE TABLE elmah.errors;
```

**2b. Delete older than N days, in batches.** Batching keeps the transaction log and locks small, so the live app keeps logging:
```sql
DECLARE @cutoff datetime = DATEADD(day, -90, GETUTCDATE());
DECLARE @app nvarchar(60);
DECLARE apps CURSOR LOCAL FAST_FORWARD FOR SELECT DISTINCT application FROM elmah.errors;
OPEN apps; FETCH NEXT FROM apps INTO @app;
WHILE @@FETCH_STATUS = 0
BEGIN
    WHILE 1 = 1
    BEGIN
        -- TABLOCK lets a heap delete deallocate the emptied pages
        DELETE TOP (5000) FROM elmah.errors WITH (TABLOCK)
        WHERE application = @app AND time_utc < @cutoff;
        IF @@ROWCOUNT = 0 BREAK;
    END
    FETCH NEXT FROM apps INTO @app;
END
CLOSE apps; DEALLOCATE apps;

-- refs whose error is gone (no FK, so clean up explicitly)
WHILE 1 = 1
BEGIN
    DELETE TOP (5000) r FROM elmah.error_refs r
    WHERE NOT EXISTS (SELECT 1 FROM elmah.errors e WHERE e.error_id = r.error_id);
    IF @@ROWCOUNT = 0 BREAK;
END
```
Long runs can exceed the query timeout, so run it with `sqlcmd -t 0`.

**3. Reclaim space (optional, off-peak):** `ALTER TABLE elmah.errors REBUILD;`. Only shrink the database if the user explicitly asks.

## PostgreSQL

**1. Size it up:**
```sql
SELECT application, COUNT(*), MIN(time_utc), MAX(time_utc) FROM elmah.errors GROUP BY application;
SELECT pg_size_pretty(pg_total_relation_size('elmah.errors'));
```

**2a. Delete everything:** `TRUNCATE elmah.error_refs, elmah.errors;`

**2b. Delete older than N days, in batches.** This needs PostgreSQL 11 or later, and must run outside an explicit transaction so `COMMIT` works:
```sql
DO $$
DECLARE cutoff timestamp := (now() at time zone 'utc') - interval '90 days'; n int;
BEGIN
  LOOP
    DELETE FROM elmah.errors WHERE error_id IN (
      SELECT error_id FROM elmah.errors WHERE time_utc < cutoff LIMIT 5000);
    GET DIAGNOSTICS n = ROW_COUNT;
    COMMIT;
    EXIT WHEN n = 0;
  END LOOP;
  DELETE FROM elmah.error_refs r WHERE NOT EXISTS (
    SELECT 1 FROM elmah.errors e WHERE e.error_id = r.error_id);
END $$;
```

**3. Reclaim space:** `VACUUM (ANALYZE) elmah.errors;`. Use `VACUUM FULL` only off-peak, because it locks the table.
