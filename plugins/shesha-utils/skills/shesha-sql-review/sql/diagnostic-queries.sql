-- BoxFusion system diagnosis: SQL Server checks. Run against a LOCAL copy (QA, or an approved production copy).
-- Read-only. Output is schema facts and counts, never row contents.
-- Run with: sqlcmd -S . -E -C -I -W -s"|" -d <db> -i <this file>   (-I is needed for tables with filtered or computed indexes; -Q breaks on the leading comment)
SET NOCOUNT ON;

-------------------------------------------------------------------------------
-- §1  Integrity: disabled or untrusted constraints, disabled triggers
-------------------------------------------------------------------------------
SELECT 'FK disabled' AS issue, OBJECT_SCHEMA_NAME(parent_object_id) + '.' + OBJECT_NAME(parent_object_id) AS tbl, name FROM sys.foreign_keys WHERE is_disabled = 1
UNION ALL SELECT 'FK untrusted', OBJECT_SCHEMA_NAME(parent_object_id) + '.' + OBJECT_NAME(parent_object_id), name FROM sys.foreign_keys WHERE is_not_trusted = 1 AND is_disabled = 0
UNION ALL SELECT 'CHECK disabled/untrusted', OBJECT_SCHEMA_NAME(parent_object_id) + '.' + OBJECT_NAME(parent_object_id), name FROM sys.check_constraints WHERE is_disabled = 1 OR is_not_trusted = 1
UNION ALL SELECT 'trigger disabled', OBJECT_SCHEMA_NAME(parent_id) + '.' + OBJECT_NAME(parent_id), name FROM sys.triggers WHERE parent_class = 1 AND is_disabled = 1;

-------------------------------------------------------------------------------
-- §2  Foreign keys whose columns are not the leading column of any index
-------------------------------------------------------------------------------
SELECT OBJECT_SCHEMA_NAME(fk.parent_object_id) + '.' + OBJECT_NAME(fk.parent_object_id) AS tbl, fk.name AS fk, COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS col,
       (SELECT SUM(p.rows) FROM sys.partitions p WHERE p.object_id = fk.parent_object_id AND p.index_id IN (0,1)) AS rows
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id AND fkc.constraint_column_id = 1
WHERE NOT EXISTS (
    SELECT 1 FROM sys.index_columns ic
    WHERE ic.object_id = fkc.parent_object_id AND ic.column_id = fkc.parent_column_id AND ic.key_ordinal = 1)
ORDER BY rows DESC;

-------------------------------------------------------------------------------
-- §3  Heaps, and clustered keys on uniqueidentifier (fragmentation-prone on large tables)
-------------------------------------------------------------------------------
SELECT SCHEMA_NAME(t.schema_id) + '.' + t.name AS tbl, 'heap' AS issue, SUM(p.rows) AS rows
FROM sys.tables t JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id = 0
GROUP BY t.schema_id, t.name
UNION ALL
SELECT SCHEMA_NAME(t.schema_id) + '.' + t.name, 'clustered on uniqueidentifier', SUM(p.rows)
FROM sys.tables t
JOIN sys.indexes i ON i.object_id = t.object_id AND i.index_id = 1
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = 1 AND ic.key_ordinal = 1
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id = 1
WHERE TYPE_NAME(c.user_type_id) = 'uniqueidentifier'
GROUP BY t.schema_id, t.name
HAVING SUM(p.rows) > 100000
ORDER BY rows DESC;

-------------------------------------------------------------------------------
-- §4  Anti-pattern scan over procedures, functions, views, triggers (counts per module; review each hit by hand;
--     catch_all_where is noisy, and needs_2016_2017 excludes LTRIM/RTRIM)
-------------------------------------------------------------------------------
SELECT OBJECT_SCHEMA_NAME(m.object_id) + '.' + OBJECT_NAME(m.object_id) AS module, o.type_desc,
    CASE WHEN m.definition LIKE '%CURSOR%' THEN 1 ELSE 0 END AS cursor_,
    CASE WHEN m.definition LIKE '%WHILE%' THEN 1 ELSE 0 END AS while_loop,
    CASE WHEN m.definition LIKE '%NOLOCK%' OR m.definition LIKE '%READ UNCOMMITTED%' THEN 1 ELSE 0 END AS nolock,
    CASE WHEN m.definition LIKE '%SELECT *%' OR m.definition LIKE '%SELECT  *%' THEN 1 ELSE 0 END AS select_star,
    CASE WHEN m.definition LIKE '%LIKE ''[%]''%' OR m.definition LIKE '%LIKE ''%''''[%]%' OR m.definition LIKE '%''[%]'' +%' THEN 1 ELSE 0 END AS leading_wildcard,
    CASE WHEN m.definition LIKE '%EXEC(%' OR m.definition LIKE '%EXEC (%' OR m.definition LIKE '%EXECUTE(%' THEN 1 ELSE 0 END AS dynamic_exec,
    CASE WHEN m.definition LIKE '%sp_executesql%' THEN 1 ELSE 0 END AS sp_executesql,
    CASE WHEN o.type IN ('P','FN','IF','TF') AND m.definition LIKE '%@% IS NULL OR %' THEN 1 ELSE 0 END AS catch_all_where,
    CASE WHEN m.definition NOT LIKE '%NOCOUNT ON%' AND o.type = 'P' THEN 1 ELSE 0 END AS no_nocount,
    CASE WHEN o.type = 'P' AND (m.definition LIKE '%UPDATE %' OR m.definition LIKE '%DELETE %') AND m.definition NOT LIKE '%BEGIN TRY%' THEN 1 ELSE 0 END AS write_no_try,
    CASE WHEN m.definition LIKE '%STRING_AGG%' OR m.definition LIKE '%OPENJSON%' OR m.definition LIKE '%[^LR]TRIM(%' THEN 1 ELSE 0 END AS needs_2016_2017,
    LEN(m.definition) AS length
FROM sys.sql_modules m JOIN sys.objects o ON o.object_id = m.object_id
WHERE o.is_ms_shipped = 0
ORDER BY (CASE WHEN m.definition LIKE '%CURSOR%' THEN 1 ELSE 0 END + CASE WHEN m.definition LIKE '%NOLOCK%' THEN 1 ELSE 0 END) DESC, length DESC;

-- Scalar UDFs (row-by-row cost when used in SELECT/WHERE over many rows)
SELECT OBJECT_SCHEMA_NAME(object_id) + '.' + name AS scalar_function FROM sys.objects WHERE type = 'FN' AND is_ms_shipped = 0;

-------------------------------------------------------------------------------
-- §5  Largest tables (growth and retention candidates)
-------------------------------------------------------------------------------
-- Rows come from sys.partitions alone: joining allocation units first would count rows once per unit (in-row, LOB, overflow)
SELECT TOP 30 SCHEMA_NAME(t.schema_id) + '.' + t.name AS tbl,
       (SELECT SUM(p.rows) FROM sys.partitions p WHERE p.object_id = t.object_id AND p.index_id IN (0,1)) AS rows,
       CAST((SELECT SUM(a.total_pages) FROM sys.partitions p JOIN sys.allocation_units a ON a.container_id = p.partition_id
             WHERE p.object_id = t.object_id) * 8 / 1024.0 AS decimal(12,1)) AS total_mb
FROM sys.tables t ORDER BY total_mb DESC;

-------------------------------------------------------------------------------
-- §6  Dead-object candidates: modules nothing in the database depends on (then grep the code for the name).
--     Views mapped by an ORM entity also appear here; exclude those whose name matches an entity's [Table]/view mapping.
-------------------------------------------------------------------------------
SELECT OBJECT_SCHEMA_NAME(o.object_id) + '.' + o.name AS module, o.type_desc, o.modify_date
FROM sys.objects o
WHERE o.type IN ('P','FN','IF','TF','V') AND o.is_ms_shipped = 0
  AND NOT EXISTS (SELECT 1 FROM sys.sql_expression_dependencies d WHERE d.referenced_id = o.object_id)
ORDER BY o.modify_date;

-------------------------------------------------------------------------------
-- §7  Index overview per large table (duplicates / overlapping leading keys)
-------------------------------------------------------------------------------
SELECT OBJECT_SCHEMA_NAME(i.object_id) + '.' + OBJECT_NAME(i.object_id) AS tbl, i.name AS idx, i.type_desc, i.is_unique, i.has_filter,
       STUFF((SELECT ', ' + COL_NAME(ic.object_id, ic.column_id) + CASE WHEN ic.is_included_column = 1 THEN ' (incl)' ELSE '' END
              FROM sys.index_columns ic WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id
              ORDER BY ic.is_included_column, ic.key_ordinal FOR XML PATH('')), 1, 2, '') AS cols
FROM sys.indexes i
WHERE OBJECTPROPERTY(i.object_id, 'IsUserTable') = 1 AND i.index_id > 0
  AND (SELECT SUM(p.rows) FROM sys.partitions p WHERE p.object_id = i.object_id AND p.index_id IN (0,1)) > 100000
ORDER BY tbl, cols;

-------------------------------------------------------------------------------
-- §8  Server facts that affect migrations
-------------------------------------------------------------------------------
SELECT DB_NAME() AS db, compatibility_level, (SELECT @@VERSION) AS local_engine_note FROM sys.databases WHERE name = DB_NAME();
-- A copy can't show production's engine version or edition: ask for SELECT @@VERSION, SERVERPROPERTY('Edition') from production.

-------------------------------------------------------------------------------
-- §9  Only with approved READ access to production: missing-index DMVs and Query Store top queries
-------------------------------------------------------------------------------
-- SELECT TOP 25 d.statement, d.equality_columns, d.inequality_columns, d.included_columns,
--        s.user_seeks, s.user_scans, s.avg_user_impact
-- FROM sys.dm_db_missing_index_details d
-- JOIN sys.dm_db_missing_index_groups g ON g.index_handle = d.index_handle
-- JOIN sys.dm_db_missing_index_group_stats s ON s.group_handle = g.index_group_handle
-- WHERE d.database_id = DB_ID() ORDER BY s.avg_user_impact * (s.user_seeks + s.user_scans) DESC;
--
-- SELECT TOP 25 qt.query_sql_text, SUM(rs.count_executions) execs,
--        SUM(rs.avg_duration * rs.count_executions) / 1000 total_ms, MAX(rs.avg_logical_io_reads) max_avg_reads
-- FROM sys.query_store_query_text qt JOIN sys.query_store_query q ON q.query_text_id = qt.query_text_id
-- JOIN sys.query_store_plan p ON p.query_id = q.query_id JOIN sys.query_store_runtime_stats rs ON rs.plan_id = p.plan_id
-- GROUP BY qt.query_sql_text ORDER BY total_ms DESC;
-- (query_sql_text contains no literal values when parameterised; still never paste parameter values into reports)

-------------------------------------------------------------------------------
-- §10 Template: sequence / reference-number gaps per month (lost-write proxy). Replace <table>, <ref column>, <number expression>.
-------------------------------------------------------------------------------
-- WITH n AS (SELECT CreationTime, <number expression> AS num FROM <table>),
--      g AS (SELECT CreationTime, num - LAG(num) OVER (ORDER BY num) - 1 AS missing FROM n)
-- SELECT FORMAT(CreationTime, 'yyyy-MM') AS month, SUM(CASE WHEN missing > 0 AND missing < 1000 THEN missing ELSE 0 END) AS missing_numbers
-- FROM g GROUP BY FORMAT(CreationTime, 'yyyy-MM') ORDER BY month;
