# run-acceptance.ps1 — the determinism acceptance test (operating-standard.md §0).
# The TWO operator runs are launched by the orchestrator (two independent `--security-only --static`
# Agent invocations in ONE message, each handed the SAME manifest.json + repo, each emitting
# findings.json to its own folder, neither able to see the other). This script does the
# normalize + diff once both findings.json exist.
#
# Usage:
#   pwsh harness/run-acceptance.ps1 -Harness <dir with run-A\ and run-B\ each holding findings.json + manifest.json>
param(
  [string]$Harness = "C:\Dev\tlc-skill-dev\harness",
  [string]$Skill   = "C:\Users\Igor Kors\.claude\skills\boxfusion-tlc\harness"
)
$ErrorActionPreference = "Stop"
foreach ($op in @("A","B")) {
  $f = Join-Path $Harness "run-$op\findings.json"
  if (-not (Test-Path $f)) { Write-Error "missing $f — the orchestrator must launch operator $op first"; exit 2 }
  node (Join-Path $Skill "normalize.mjs") $f | Out-File -Encoding utf8 (Join-Path $Harness "run-$op\findings.norm.json")
}
node (Join-Path $Skill "diff-findings.mjs") `
  (Join-Path $Harness "run-A\findings.norm.json") `
  (Join-Path $Harness "run-B\findings.norm.json") `
  (Join-Path $Harness "run-A\manifest.json") `
  (Join-Path $Harness "run-B\manifest.json")
$code = $LASTEXITCODE
if ($code -eq 0) { Write-Host "ACCEPTANCE: PASS — findings + fix order converged." }
else { Write-Host "ACCEPTANCE: DIVERGED — see onlyA/onlyB above; each is a determinism defect to re-engineer." }
exit $code
