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

Disk-full alerts often name the **App Service plan** (e.g. `midvaal-cep-prod-01`), not the app. If no app matches, look the name up as a plan and list its apps:
```bash
az webapp list --subscription "<sub>" --query "[?ends_with(appServicePlanId,'/<plan>')].{name:name,state:state}" -o table
```
Every app on a plan shares one storage quota (250 GB on P3v3), so another app's logs can fill it. Check the plan's usage, which is read-only and fast:
```bash
az rest --method get --url "https://management.azure.com/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Web/serverfarms/<plan>/usages?api-version=2022-03-01" \
  --query "value[?name.value=='FileSystemStorage'].{used:currentValue,limit:limit}" -o table
```

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
- For any `exec` script containing single quotes (XPath, regex), pass it from a quoted heredoc: `read -r -d '' PS <<'EOF' ... EOF; bash $K ... exec "$PS"`. Inside a bash single-quoted string, PowerShell's `''` escape is silently dropped and the script runs with the wrong logic.
- Never use `ls` in a huge Elmah folder. It reads the whole directory before printing, so even `ls | head` times out. Use `find ... | head` (Linux) or `[IO.Directory]::EnumerateFiles(...) | Select -First N` (Windows), which stream.

### Disk already at 0 bytes free

`start` uploads the job script first, so on a full disk it fails with `There is not enough space on the disk`. Free a little room first with a bounded `exec` that deletes the oldest files past the cutoff, judged by the date in the filename, for at most 140 s, and tallies the types of the first few hundred as it goes. Get the user's OK first. It's still a delete. On Windows:
```bash
bash $K <app> <rg> "<sub>" exec '$sw=[Diagnostics.Stopwatch]::StartNew(); $cut="<yyyy-MM-dd>"; $d=0; $b=0; $t=@{}; foreach($f in [IO.Directory]::EnumerateFiles("<dir>","error-*.xml")){ if([IO.Path]::GetFileName($f).Substring(6,10) -ge $cut){continue}; if($d -lt 300){ $l=[IO.File]::ReadLines($f) | Select -First 1; if($l -match " type=""([^""]*)"""){ $t[$matches[1]]=1+$t[$matches[1]] } }; $fi=New-Object IO.FileInfo $f; $b+=$fi.Length; $fi.Delete(); $d++; if($sw.Elapsed.TotalSeconds -gt 140){break} }; "deleted=$d freed_mb=$([int]($b/1MB))"; $t.GetEnumerator() | Sort Value -Desc | % { "$($_.Value) $($_.Name)" }'
```
One pass freed about 80 MB (2,400 files of about 34 KB) on midvaal. That's plenty for the job script. Then go straight to `start delete`, because a histogram over millions of files can take hours while the apps keep failing.

Free-space readings lag and jump around during a big delete. On midvaal the plan `usages` API flipped between 0, 67 MB and 3.9 GB within minutes, and once jumped to 225 GB free. Don't diagnose a "hidden writer" from them. Use the job's `progress`, plus `[IO.DriveInfo]"D:\"` through `exec` for a direct reading. To check whether another app on the plan really is writing, compare each app's `FileSystemUsage` metric (only `PT6H` or coarser grains are allowed) and look for files modified in the last hour under each app's `D:/home`.

### Understand the errors first

Before deleting, read the first lines of a sample of the newest files and tally them by `type` and `message`. Each file's first line is `<error ... type="..." message="..." source="..." time="...">`. On Linux:
```bash
bash $K <app> <rg> "<sub>" exec 'cd <dir>; timeout 150 find . -maxdepth 1 -type f -iname "*.xml" | head -3000 | xargs head -q -n 1 | sed -E "s/.* type=\"([^\"]*)\" message=\"([^\"]{0,120}).*/\1 | \2/" | sort | uniq -c | sort -rn | head'
```
Share the top error types with the user, because the flood will come back unless its cause is fixed. The first line shows only the outer exception, so read one whole file (`[xml]` → `.error.detail`) for the inner cause, and redact connection strings before showing it. On classic ASP.NET (.NET Framework) apps, a "MongoDB server selection timeout" whose `HeartbeatException` is `FileLoadException: System.Memory, Version=4.0.1.2` is a missing binding redirect, not a network problem. Compare `[Reflection.AssemblyName]::GetAssemblyName()` of the `bin` DLL with the `web.config` `<dependentAssembly>` entries.

When done, report `matched`, `xml_files_remaining` and (on Linux) the `df` line from `status`.

### Stop it coming back

Classic ELMAH 1.2's `XmlFileErrorLog` (`<errorLog type="Elmah.XmlFileErrorLog, Elmah" logPath="~/App_Data/ElmahLogs" />` in `web.config`) has **no file count, size or age limit**. With the user's approval, offer these:

- **Nightly cleanup WebJob (Windows):** `bash $K <app> <rg> "<sub>" webjob-install` installs [assets/elmah-cleanup-webjob](assets/elmah-cleanup-webjob) as the triggered WebJob `elmah-cleanup`. It runs at 02:00 in `WEBSITE_TIME_ZONE` (UTC if that isn't set) and keeps 30 days, or `ELMAH_RETENTION_DAYS` if that app setting exists. It needs **Always On**. It lives in `App_Data/jobs`, which release pipelines leave alone when they use Web Deploy with "Exclude files from App_Data", so redeploys don't remove it. Check it with `webjob-status`.
- **Disk alert:** the App Service plan has no storage metric, so put a metric alert on the app's `FileSystemUsage` (`--window-size 6h`, because finer grains are rejected), routed to the plan's existing alert action group. The plan quota also counts small-file overhead: midvaal's plan read 250/250 GB while `FileSystemUsage` read 88 GB. Set the threshold against that ratio, and create the rule `--disabled true` until a cleanup brings the metric under the threshold.
- Don't filter error types out in `<errorFilter>` just to save disk. The flood is the symptom you want to see.

Changing the app's own `web.config` or store (for example to Shesha.Elmah SQL) needs an explicit ask.

## Step 3: Database store

Apps whose `Startup.cs` calls `services.AddSheshaElmah(...)` log to `elmah.errors` in their `Default` database; `services.AddElmah<XmlFileErrorLog>` means XML files. Prod SQL firewalls usually block developer IPs, so `kudu-elmah.sh` runs the SQL job **on the app side** with the app's own connection string (Node + `mssql` on Linux Kudu, installed into the work dir on first use; PowerShell + SqlClient on Windows):
```bash
bash $K <app> <rg> "<sub>" sql-start histogram 30        # size, rows per app/month, top error types older/recent
bash $K <app> <rg> "<sub>" sql-start count 30            # rows older than 30 days
bash $K <app> <rg> "<sub>" sql-status                    # poll; progress = rows deleted so far
bash $K <app> <rg> "<sub>" sql-start delete 30 [5000]    # only after user confirms; batches of 5000
bash $K <app> <rg> "<sub>" sql-stop
```
The histogram's `top_types_older` is the error tally to share before deleting. The delete goes one application at a time in short batches (the live app keeps logging), then removes orphaned `error_refs`. Several apps often share one database, so check `rows_by_application` and run the job once per database. `elmah_mb` barely drops after a delete: `all_xml` lives in LOB pages that stay allocated to the heap. New errors reuse that space, so the database stops growing, but giving it back needs `ALTER TABLE elmah.errors REBUILD` off-peak (or `TRUNCATE` when `rows_remaining=0`), which is a separate, user-approved step. Size the batch from the histogram: `elmah_mb` ÷ rows gives the average row size, and a batch should stay around 250 MB of log (the default 5000 suits typical 20–50 KB rows; dsd-npo's ~530 KB rows needed 500). SQL Server only; for PostgreSQL, or to run statements by hand, see [reference/sql-store.md](reference/sql-store.md).

## Report

Summarise per store: what was found (count, date range, top error types, size), what was deleted, what remains, and disk/DB space before and after.
