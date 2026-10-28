---
name: delete-app-logs
description: Surveys and deletes old application log files from deployed Shesha/.NET apps on Linux or Windows Azure App Services, in App_Data/Logs. That covers the rolled log4net files (App_<host>.log*) and Shesha scheduled-job run logs (App_Data/Logs/jobs/<JobName>/*.log). Cleanup runs through the Kudu API as a detached, resumable server-side job with an age cutoff, and a fleet survey ranks which apps' logs take the most space. Use when asked to clean up, purge, trim or delete app logs, log4net logs, scheduled job logs or job execution logs, to free App Service disk space taken by logs, or to find which apps have the biggest log folders. For Elmah error logs use delete-elmah-logs instead.
---

# Delete App Logs

Shesha apps write two kinds of file into `App_Data/Logs`. That's `/home/site/wwwroot/App_Data/Logs` on Linux and `D:/home/site/wwwroot/App_Data/Logs` on Windows; the folder name can be `logs` in lowercase. Neither kind cleans itself up:

| Kind | Path | Why it grows |
|---|---|---|
| **Rolled main logs** | `Logs/App_<host>.log`, `.log.1` … `.log.10` | log4net's `RollingFileAppender` caps each file name at 10 × 10 MB. But the name comes from a `FilePatternConverter` that uses `COMPUTERNAME`/`HOSTNAME`. On Linux that's the container ID, which **changes on every restart or deploy**, so each restart starts a fresh ~110 MB set and the old sets are never removed. |
| **Job run logs** | `Logs/jobs/<JobName>/<yyyy-MM-dd_HHmmss>_<executionId>.log` | `ScheduledJobBase` writes one file per run, under `~/App_Data/logs/jobs` (or the `DefaultLogFolder` setting). Nothing deletes them. Verbose import jobs can write hundreds of MB per run. |

What deleting them affects:
- Each `ScheduledJobExecution` row stores its `LogFilePath`, and the admin UI's job-execution log viewer reads the file from disk. After deletion, old executions just show no log, and the execution rows themselves are untouched. Jobs with `LogMode.StoredFile` also keep a copy as a StoredFile, which this skill doesn't touch.
- The active main log is still being written. The job scripts refuse a cutoff under 1 day, and the default retention keeps recent files anyway.

## Safety rules

- This is production data deletion. **Always `survey` and `count` first**, show the user the numbers (files, MB, oldest month per folder), and get explicit confirmation of the app, folder and age cutoff before any delete.
- Default retention is **30 days** unless the user asks otherwise. Never go below 1 day.
- Stay inside `App_Data/Logs` (or a subfolder of it). Elmah XML has its own skill (`delete-elmah-logs`). Don't touch Elmah folders, `/home/LogFiles` platform logs, or anything else.
- Never print connection strings or app-setting values.

## Workflow

`scripts/kudu-logs.sh <app> <rg> <subscription> <action> [args]` reads the app's `kind` and drives bash (Linux) or PowerShell 5.1 (Windows) through Kudu. Run it with bash (Git Bash on Windows).

```bash
K=<skill-dir>/scripts/kudu-logs.sh
bash $K <app> <rg> "<sub>" survey                                   # total, top-level files, biggest job/sub folders
bash $K <app> <rg> "<sub>" start count  <logs-dir> <days> [pattern]  # dry run: files + MB older than <days>
bash $K <app> <rg> "<sub>" status                                   # poll; progress_files_mb = "<files> <MB>"
bash $K <app> <rg> "<sub>" start delete <logs-dir> <days> [pattern]  # only after user confirms
bash $K <app> <rg> "<sub>" stop
bash $K <app> <rg> "<sub>" exec "<bash or PowerShell>"
```
- `<logs-dir>` is matched recursively. Use the whole `.../App_Data/Logs` folder for a general cleanup, or one folder such as `.../App_Data/Logs/jobs/CsdImportJob` to target a single job. Use forward slashes on Windows too.
- `[pattern]` is a file-name glob (default `*`). For example, `'App_*'` limits the cleanup to the rolled main logs.
- The jobs run detached (`nohup setsid` / `Start-Process`) because Kudu kills any request after about 230 s. They're idempotent, so if a job dies (`alive=no` while `state=running`), start it again. Only one runs per app at a time.
- Commands go to Kudu encoded (base64 / `-EncodedCommand`), because raw quotes and backslashes give HTTP 400 on Windows. Windows Kudu runs PowerShell 5.1, so avoid 7-only syntax.

## Fleet survey

To find which apps need it, take the prod app list from the Airtable base **Repos & Modules** (table **Repos**, field **Azure Prod Apps**) and resolve each app's subscription, resource group and kind with `az webapp list`. Then run `survey` on every API, but not the portals, which have no backend logs. Run about 4–8 at a time, and write each app's output to its own file. Rank by `TOTAL_MB` and show the biggest job folders. Apps whose survey times out have very large folders, so retry them on their own.

## Report

For each app, report the size before, what was deleted (files and MB, by folder), the size after, and the job folders that dominate. Then point out the fixes that would stop the growth, and only make them if the user asks:
- **Job logs:** turn down a noisy job's logging, or add a retention cleanup job.
- **Main logs:** give `FilePatternConverter` a stable name (no host) so log4net's 10 × 10 MB cap actually holds, or log to stdout or Application Insights instead.
