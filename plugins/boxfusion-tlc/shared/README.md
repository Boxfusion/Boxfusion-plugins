# tlc-core — the shared determinism & quality contract

This folder is the **single source of truth** for everything the TLC collection shares. The conductor (`boxfusion-tlc`) and every division review skill in this plugin reference these files; **none of them copies this content**. That is what keeps the acceptance guarantee alive: two runs on the same commit + manifest produce byte-identical `findings.json`, because every skill reads the *same* contract.

## How to reference it from a skill

In any skill's `SKILL.md` in this plugin, point at these files with the plugin-root variable (Claude Code substitutes the real cache path at load time — forward slashes on every OS):

```
${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md
${CLAUDE_PLUGIN_ROOT}/shared/briefs/inspector-briefs-and-partitions.md
${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md
```

Never copy a file out of `shared/` into a skill folder, and never use `../` or absolute paths to reach it — the variable is the only supported, cache-safe way.

## Contents

| File | What it is |
|---|---|
| `operating-standard.md` | The determinism & quality contract, §0–9: reproducibility target, capability manifest, checks-as-decision-procedures, stable IDs (`CHECK-ID@anchor`), the closed evidence enum, scored severity, templated remediation, the agent-briefing standard, `findings.json` normalization, the sampling firewall. |
| `briefs/inspector-briefs-and-partitions.md` | The canonical security + generic-division inspector briefs (fill only the placeholders), the fixed sub-area partitions, and the orchestration rules (overlap resolution, duplicate-collapse-by-id, persist-then-derive, the two-operator acceptance diff). |
| `framework-standards.md` | The Shesha / ABP native mechanism for each kind of fix, plus known caveats. |
| `safety-and-data-access.md` | QA-first, production escalation, isolation + canary, PII rules, synthetic logins, and the secret-redaction rule. |
| `templates/finding.md`, `templates/report.md`, `templates/shesha-team-report.md` | The finding, report and Shesha-team-report shapes. |
| `harness/normalize.mjs`, `harness/diff-findings.mjs`, `harness/run-acceptance.ps1` | The normalizer + differ + acceptance runner: launch two independent operators on the same manifest and diff their `findings.json`. The regression gate for any contract or check change. |

## Versioning

A change here reaches installed users only when the plugin `version` bumps. Stamp `contract_version` into `findings.json` so a division built against an older contract is detectable; the conductor refuses a division whose contract version it doesn't support.
