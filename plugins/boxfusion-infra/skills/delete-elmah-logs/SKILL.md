---
name: delete-elmah-logs
description: Deletes accumulated Elmah error logs from deployed Shesha/.NET apps. It handles both storage modes. XML files on a Linux or Windows Azure App Service (e.g. App_Data/ElmahLogs) are deleted through the Kudu API with a detached, resumable server-side job, which copes with millions of files. Database rows (Shesha.Elmah's elmah.errors / elmah.error_refs on SQL Server or PostgreSQL) are deleted with batched deletes or truncates. It can also triage a fleet of prod apps to find which ones have the biggest Elmah backlog. Use when asked to delete, purge, clean up, clear or trim Elmah logs, Elmah XML files or the elmah errors table, to free disk/DB space taken by Elmah, or to find which apps need an Elmah cleanup.
---

# Delete Elmah Logs

Elmah logs are stored in one of two places:

| Store | Where | How to clean |
|---|---|---|
| **XML files** | Each error is a `*.xml` file, usually in `App_Data/ElmahLogs` under the site root: `/home/site/wwwroot` on Linux, `D:/home/site/wwwroot` on Windows | `scripts/kudu-elmah.sh` (this file) |
| **Database** | `elmah.errors` + `elmah.error_refs` (Shesha.Elmah, `Default` connection string) | [reference/sql-store.md](reference/sql-store.md) |

An app can use both, for example an older XML log next to the newer SQL log. Check for both and clean each one the user wants.

To pick which apps to clean across many prod apps, follow [reference/fleet-triage.md](reference/fleet-triage.md) first.

## Safety rules

- This is production data deletion. **Always do a histogram/count dry run first.** Show the user the numbers (total, matched by age, months), then get explicit confirmation of the exact target (app, store, age cutoff) before any delete.
- Default retention is **30 days** (delete only files/rows older than 30 days) unless the user asks for another cutoff or to delete everything.
- **Tally the error types before deleting.** Once the files are gone, so is the evidence of what caused the flood. Sample the newest files (see "Understand the errors first").
- Never print connection strings, passwords or app-setting values. Listing setting *names* is fine.
- Delete only Elmah data: `*.xml` in the Elmah folder, or the `elmah` schema tables. Nothing else. Other disk hogs, such as Shesha scheduled-job logs in `App_Data/Logs/jobs`, are out of scope. Report them, but don't delete them.

## Step 1: Identify the app

Gather the app name, resource group and subscription. If only the name is known, search the subscriptions. Prod apps often live in a different subscription from dev/test ones:
```bash
az webapp list --subscription "<sub>" --query "[?contains(name,'<fragment>')].{name:name,rg:resourceGroup,kind:kind}" -o table
```
`kudu-elmah.sh` reads `kind` itself and switches between Linux (bash) and Windows (PowerShell 5.1) automatically.

## Step 2: XML files on an App Service

`scripts/kudu-elmah.sh <app> <rg> <subscription> <action> [args]` uses an `az` login token against `https://<app>.scm.azurewebsites.net`. Run it with bash (Git Bash on Windows).

```bash
K=<skill-dir>/scripts/kudu-elmah.sh
bash $K <app> <rg> "<sub>" probe                                  # elmah folders (+ df on Linux)
bash $K <app> <rg> "<sub>" start histogram <dir> 0                # files per month (by mtime)
bash $K <app> <rg> "<sub>" start count  <dir> <days>              # dry run (0 days = all files)
bash $K <app> <rg> "<sub>" status                                 # poll; progress = files matched so far
bash $K <app> <rg> "<sub>" start delete <dir> <days>              # only after user confirms
bash $K <app> <rg> "<sub>" stop                                   # abort a running job
bash $K <app> <rg> "<sub>" exec "<bash or PowerShell>"            # short ad-hoc command
```
`<dir>` is `/home/site/wwwroot/App_Data/ElmahLogs` on Linux and `D:/home/site/wwwroot/App_Data/ElmahLogs` on Windows. Use forward slashes on Windows too.

Why it works this way:
- **Kudu kills any `/api/command` request after about 230 s.** With over a million files, even `ls | wc -l` or `du` times out. So `start` uploads the job script (`elmah-xml-cleanup.sh` or `elmah-xml-cleanup.ps1`) to `LogFiles/elmah-cleanup/` and launches it detached (`nohup setsid` on Linux, `Start-Process` on Windows), and the call returns at once. `status` reads the `status`/`progress` files the job writes.
- Both jobs stream directory entries (`find -maxdepth 1` on Linux, `EnumerateFiles` on Windows), with no globbing or sorting, so memory stays flat.
- `/home` is an SMB share. Expect a few hundred files per second (Lesedi: 1.6M files in about 85 min). Poll with `status` every few minutes and don't call it in a tight loop.
- The job is **idempotent and resumable**. If the Kudu container recycles (`alive=no` while `state=running`), run the same `start` again and it continues with whatever is left.
- Only one job runs at a time per app (pid file guard).
- Run `histogram` before `count`. Error bursts can produce 100k+ files a day, so most files may fall inside the retention window. File mtimes match the timestamp in the Elmah filename (`error-YYYY-MM-DDhhmmssZ-<guid>.xml`).
- Commands are sent encoded (base64 into bash, or PowerShell `-EncodedCommand`) because raw quotes and backslashes break Kudu's JSON (Windows answers HTTP 400). Windows Kudu runs PowerShell **5.1**, so avoid 7-only syntax (`-AsUTC`, `??`, `?.`).
- Never use `ls` in a huge Elmah folder. It reads the whole directory before printing, so even `ls | head` times out. Use `find ... | head` (Linux) or `[IO.Directory]::EnumerateFiles(...) | Select -First N` (Windows), which stream.

### Understand the errors first

Before deleting, read the first lines of a sample of the newest files and tally them by `type` and `message`. Each file's first line is `<error ... type="..." message="..." source="..." time="...">`. On Linux:
```bash
bash $K <app> <rg> "<sub>" exec 'cd <dir>; timeout 150 find . -maxdepth 1 -type f -iname "*.xml" | head -3000 | xargs head -q -n 1 | sed -E "s/.* type=\"([^\"]*)\" message=\"([^\"]{0,120}).*/\1 | \2/" | sort | uniq -c | sort -rn | head'
```
Share the top error types with the user, because the flood will come back unless its cause is fixed.

When done, report `matched`, `xml_files_remaining` and (on Linux) the `df` line from `status`.

Optional follow-up: suggest stopping the growth at its source, through XML retention in app config or moving to Shesha.Elmah's SQL store. Do not change app config without being asked.

## Step 3: Database store

Follow [reference/sql-store.md](reference/sql-store.md). It covers locating the connection string without exposing it, sizing queries, `TRUNCATE` for delete-all, batched age-based deletes for SQL Server and PostgreSQL, orphaned `error_refs` cleanup and space reclaim.

## Report

Summarise per store: what was found (count, date range, top error types, size), what was deleted, what remains, and disk/DB space before and after.
