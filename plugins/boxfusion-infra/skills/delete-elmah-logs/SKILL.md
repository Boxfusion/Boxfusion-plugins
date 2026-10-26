---
name: delete-elmah-logs
description: Deletes accumulated Elmah error logs from deployed Shesha/.NET apps. It handles both storage modes. XML files on a Linux Azure App Service (e.g. App_Data/ElmahLogs) are deleted through the Kudu API with a detached, resumable server-side job, which copes with millions of files. Database rows (Shesha.Elmah's elmah.errors / elmah.error_refs on SQL Server or PostgreSQL) are deleted with batched deletes or truncates. Use when asked to delete, purge, clean up, clear or trim Elmah logs, Elmah XML files or the elmah errors table, or to free disk/DB space taken by Elmah.
---

# Delete Elmah Logs

Elmah logs are stored in one of two places:

| Store | Where | How to clean |
|---|---|---|
| **XML files** | Each error is a `*.xml` file, usually in `/home/site/wwwroot/App_Data/ElmahLogs` on a Linux App Service | `scripts/kudu-elmah.sh` (this file) |
| **Database** | `elmah.errors` + `elmah.error_refs` (Shesha.Elmah, `Default` connection string) | [reference/sql-store.md](reference/sql-store.md) |

An app can use both, for example an older XML log next to the newer SQL log. Check for both and clean each one the user wants.

## Safety rules

- This is production data deletion. **Always do a count/dry run first.** Show the user the numbers (total, matched by age, oldest/newest), then get explicit confirmation of the exact target (app, store, age cutoff) before any delete.
- Default retention is **30 days** (delete only files/rows older than 30 days) unless the user asks for another cutoff or to delete everything.
- Never print connection strings, passwords or app-setting values. Listing setting *names* is fine.
- Delete only Elmah data: `*.xml` in the Elmah folder, or the `elmah` schema tables. Nothing else.

## Step 1: Identify the app

Gather the app name, resource group and subscription. If only the name is known, search the subscriptions. Prod apps often live in a different subscription from dev/test ones:
```bash
az webapp list --subscription "<sub>" --query "[?contains(name,'<fragment>')].{name:name,rg:resourceGroup,kind:kind}" -o table
```
Confirm `kind` contains `linux`. The Kudu scripts assume a Linux container. A Windows App Service needs PowerShell through Kudu instead, which these scripts do not cover.

## Step 2: XML files on a Linux App Service

`scripts/kudu-elmah.sh <app> <rg> <subscription> <action> [args]` uses an `az` login token against `https://<app>.scm.azurewebsites.net`. Run it with bash (Git Bash on Windows).

```bash
K=<skill-dir>/scripts/kudu-elmah.sh
bash $K <app> <rg> "<sub>" probe                                  # disk usage + elmah folders
bash $K <app> <rg> "<sub>" start histogram <dir> 0                # files per month (by mtime)
bash $K <app> <rg> "<sub>" start count  <dir> <days>              # dry run (0 days = all files)
bash $K <app> <rg> "<sub>" status                                 # poll; progress = files matched so far
bash $K <app> <rg> "<sub>" start delete <dir> <days>              # only after user confirms
bash $K <app> <rg> "<sub>" stop                                   # abort a running job
```

Why it works this way:
- **Kudu kills any `/api/command` request after about 230 s.** With over a million files, even `ls | wc -l` or `du` times out. So `start` uploads `scripts/elmah-xml-cleanup.sh` to `/home/LogFiles/elmah-cleanup/` and launches it with `nohup setsid`, and the call returns at once. `status` reads the `status`/`progress` files the job writes.
- The job streams `find -maxdepth 1 -type f -iname '*.xml' [-mtime +N] -delete`, with no globbing or sorting, so memory stays flat.
- `/home` is an SMB share. Expect roughly hundreds to a few thousand files per second. Poll with `status` every few minutes and don't call it in a tight loop.
- The job is **idempotent and resumable**. If the Kudu container recycles (`alive=no` while `state=running`), run the same `start delete` again and it continues with whatever is left.
- Only one job runs at a time (pid file guard).
- Run `histogram` before `count`. Error bursts can produce 100k+ files a day, so most files may fall inside the retention window. Show the user the month breakdown so the cutoff is chosen knowingly. File mtimes match the timestamp in the Elmah filename (`error-YYYY-MM-DDhhmmssZ-<guid>.xml`).
- Never use `ls` in the Elmah folder. It reads the whole directory before printing, so even `ls | head` times out. Use `find ... | head` instead, which streams.

When done, report `matched`, `xml_files_remaining` and the `df` line from `status`.

Optional follow-up: suggest stopping the growth at its source, through XML retention in app config or moving to Shesha.Elmah's SQL store. Do not change app config without being asked.

## Step 3: Database store

Follow [reference/sql-store.md](reference/sql-store.md). It covers locating the connection string without exposing it, sizing queries, `TRUNCATE` for delete-all, batched age-based deletes for SQL Server and PostgreSQL, orphaned `error_refs` cleanup and space reclaim.

## Report

Summarise per store: what was found (count, date range, size), what was deleted, what remains, and disk/DB space before and after.
