# Fleet triage: which apps need an Elmah cleanup

Use this when the user wants to prioritise across many prod apps instead of cleaning one named app.

## 1. Get the app list

The Airtable base **Repos & Modules** has a **Repos** table, and its **Azure Prod Apps** field lists each Shesha repo's prod App Service names, one per line. Its sources are the MCA Production Subscription, Boxfusion_Cloudmania_Azure_Subscription and SheshaCloudProd subscriptions. Read the **Name** and **Azure Prod Apps** fields, filtered on Azure Prod Apps being non-empty.

Resolve each name to a subscription, resource group, `kind` (Linux or Windows) and resource ID. Listing a whole subscription takes minutes, so list each one once, in parallel, and join locally:
```bash
az webapp list --subscription "<sub>" --query "[].[name,resourceGroup,kind,state,id]" -o tsv
```

## 2. Find which store each repo uses

The Repos table has an **Elmah Store** field (File / Database / Mixed) and a **Prod Database** field. To fill or refresh Elmah Store, search Azure DevOps code across the whole organisation (not per project) for both registrations, then read each prod repo's `*.Web.Host/Startup/Startup.cs`, since a match can be commented out:
```bash
T=$(az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv)
for q in XmlFileErrorLog AddSheshaElmah; do
  curl -sS -H "Authorization: Bearer $T" -H "Content-Type: application/json" -X POST \
    "https://almsearch.dev.azure.com/boxfusion/_apis/search/codesearchresults?api-version=7.1" \
    -d "{\"searchText\":\"$q ext:cs\",\"\$top\":1000,\"filters\":{}}" > $q.json
done
```
- `services.AddElmah<XmlFileErrorLog>(...)` → **File** (`App_Data/ElmahLogs`).
- `services.AddSheshaElmah(_appConfiguration)` → **Database** (Shesha.Elmah always writes to SQL; its `SheshaElmah:Path` setting is the UI route, not a folder).
- A repo with several Web.Host projects can have one of each → **Mixed**; note which prod app runs which host.

Code says what the default branch would do; an older build in prod can still differ (an XML folder still growing on a "Database" repo). Confirm on the app: XML with `start histogram`, DB with `sql-start histogram`.

## 3. Rank by disk usage

The App Service metric `FileSystemUsage` (bytes) is a fast, read-only proxy for Elmah volume. On Lesedi it dropped from 9.9 GB to 1.3 GB when 1.6M Elmah files were deleted. Compare it with a week ago to see growth:
```bash
export MSYS_NO_PATHCONV=1   # Git Bash otherwise mangles /subscriptions/... resource IDs
az monitor metrics list --resource "<id>" --metric FileSystemUsage --interval PT6H --offset 1d \
  --aggregation Average --query "value[0].timeseries[0].data[-1].average" -o tsv
```
Write each result to its own file (or collect them sequentially). Parallel `>>` appends to one file can lose lines.

Portals (admin/public) are usually large because of their frontend bundles, so they rarely hold Elmah. Focus on the APIs.

## 4. Confirm what the space actually is

A big app isn't necessarily Elmah. For the top candidates:
- List `site/wwwroot/App_Data/` through the Kudu VFS API (`GET https://<app>.scm.azurewebsites.net/api/vfs/site/wwwroot/App_Data/`, bearer token from `az account get-access-token`). Look for `ElmahLogs/`.
- Run `start histogram` from `kudu-elmah.sh` on each app that has `ElmahLogs`. It's read-only and runs detached, so you can start several apps in parallel and poll each one's `status`.
- If the Elmah count is small but the disk is big, measure the other folders. A common culprit is Shesha's scheduled-job run logs in `App_Data/Logs/jobs/<JobName>/` (one file per run, sometimes hundreds of MB each). That's outside this skill's scope, so report it.

## 5. Present a ranked table

Show the Elmah file count, months covered, disk GB, 7-day growth and OS for each app. Recommend an order (largest Elmah backlog and fastest growth first), and get confirmation per app before any delete.
