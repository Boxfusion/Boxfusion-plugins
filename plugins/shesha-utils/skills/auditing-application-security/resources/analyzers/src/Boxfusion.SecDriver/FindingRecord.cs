using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Serialization;

namespace Boxfusion.SecDriver
{
    /// <summary>
    /// A single determinism-standard.md §8 findings.json record. Property order here IS the
    /// serialized field order (System.Text.Json preserves declaration order), so two runs
    /// on the same commit are byte-identical.
    /// </summary>
    public sealed class FindingRecord
    {
        [JsonPropertyName("finding_id")] public string FindingId { get; set; } = "";
        [JsonPropertyName("check_id")] public string CheckId { get; set; } = "";
        [JsonPropertyName("area")] public string Area { get; set; } = "security";
        [JsonPropertyName("anchor")] public string Anchor { get; set; } = "";
        [JsonPropertyName("evidence_level")] public string EvidenceLevel { get; set; } = "";
        [JsonPropertyName("execution_class")] public string ExecutionClass { get; set; } = "";
        [JsonPropertyName("severity")] public string Severity { get; set; } = "";
        [JsonPropertyName("severity_inputs")] public SeverityInputs? SeverityInputs { get; set; }
        [JsonPropertyName("plan_id")] public string? PlanId { get; set; }
        [JsonPropertyName("root_cause")] public string? RootCause { get; set; }
        [JsonPropertyName("fix_order_rank")] public int? FixOrderRank { get; set; }
        [JsonPropertyName("sources")] public List<string> Sources { get; set; } = new();
        [JsonPropertyName("not_assessed_reason")] public string? NotAssessedReason { get; set; }
        [JsonPropertyName("non_deterministic")] public bool NonDeterministic { get; set; }
        [JsonPropertyName("commit_sha")] public string? CommitSha { get; set; }

        // not serialized — ordering key only
        [JsonIgnore] public int Band { get; set; }
    }

    public sealed class SeverityInputs
    {
        [JsonPropertyName("impact_class")] public string ImpactClass { get; set; } = "";
        [JsonPropertyName("reachability")] public string Reachability { get; set; } = "";
        [JsonPropertyName("data_sensitivity")] public string DataSensitivity { get; set; } = "";
    }

    /// <summary>
    /// Per-check severity inputs and scoring, keyed off the shared check registry
    /// (references/check-registry.md "New checks" rows for SEC-A / SEC-H) and the §4
    /// severity-scoring table. Severity is DERIVED from the three declared inputs via
    /// <see cref="Score"/> (determinism-standard §4 — severity is scored, not asserted).
    ///
    /// Registry reconciliation notes (see resources/analyzers/README.md):
    ///  - SEC-A reachability "n/a" in the registry is not scorable; the BOLA surface is an
    ///    authenticated endpoint, so it is resolved to `any_authenticated` (registry value).
    ///  - SEC-H reachability "n/a" (a log sink, not an endpoint gate) is resolved to
    ///    `admin_only` — the leaked PII is exposed to whoever reads the logs (operators /
    ///    admins). With the shift rule below this scores base Medium +1 = High, the
    ///    TLC-proven SEC-H severity.
    ///  - root_cause uses the registry §6 RC-sec-* vocabulary: SEC-A → RC-sec-bola
    ///    (determinism-standard §7 names SEC_A a BOLA check). SEC-H → RC-sec-pii-logging
    ///    (proposed: the registry has no registered RC for PII-in-logs yet).
    /// </summary>
    public static class CheckProfiles
    {
        public static readonly Dictionary<string, int> Band = new()
        {
            ["Critical"] = 0, ["High"] = 1, ["Medium"] = 2, ["Low"] = 3, ["Info"] = 4,
        };

        // determinism-standard §4 base(impact_class, reachability) table.
        private static readonly Dictionary<string, string[]> BaseTable = new()
        {
            //                      anonymous   any_authenticated  low_priv   admin_only  local_only
            ["auth_bypass"]      = new[] { "Critical", "High",     "High",    "Medium",   "Low" },
            ["data_exposure_pii"]= new[] { "Critical", "High",     "High",    "Medium",   "Low" },
            ["data_integrity"]   = new[] { "High",     "High",     "Medium",  "Medium",   "Low" },
            ["dos"]              = new[] { "High",     "Medium",   "Medium",  "Low",      "Low" },
            ["info_leak"]        = new[] { "High",     "Medium",   "Low",     "Low",      "Low" },
            ["maintainability"]  = new[] { "Low",      "Low",      "Low",     "Low",      "Low" },
        };

        private static readonly string[] Reach =
            { "anonymous", "any_authenticated", "low_priv", "admin_only", "local_only" };
        private static readonly string[] Ladder = { "Critical", "High", "Medium", "Low", "Info" };

        /// <summary>
        /// severity = base(impact_class, reachability), then shift one band per
        /// data_sensitivity: popia_special +1, pii_basic +1, business +0, none +0.
        /// A positive shift raises severity (toward Critical); capped at Critical.
        /// </summary>
        public static string Score(SeverityInputs inputs)
        {
            if (!BaseTable.TryGetValue(inputs.ImpactClass, out var row))
                return "Info";
            int col = Array.IndexOf(Reach, inputs.Reachability);
            if (col < 0) col = 1; // default any_authenticated when a reachability is n/a
            string baseSev = row[col];
            int idx = Array.IndexOf(Ladder, baseSev);

            int shift = inputs.DataSensitivity switch
            {
                "popia_special" => 1,
                "pii_basic" => 1,
                _ => 0,
            };
            idx -= shift;            // one step toward Critical (index 0)
            if (idx < 0) idx = 0;    // cap at Critical
            return Ladder[idx];
        }

        public static (string sev, SeverityInputs inputs, string plan, string rc) Profile(string checkId)
        {
            SeverityInputs inputs;
            string plan, rc;
            switch (checkId)
            {
                case "SEC-A":
                    inputs = new SeverityInputs
                    {
                        ImpactClass = "auth_bypass",
                        Reachability = "any_authenticated",
                        DataSensitivity = "pii_basic",
                    };
                    plan = "PLAN-SEC-A";
                    rc = "RC-sec-bola";
                    break;
                case "SEC-H":
                    inputs = new SeverityInputs
                    {
                        ImpactClass = "data_exposure_pii",
                        Reachability = "admin_only", // registry "n/a" resolved to the log-sink reader (ops/admin)
                        DataSensitivity = "pii_basic",
                    };
                    plan = "PLAN-SEC-H";
                    rc = "RC-sec-pii-logging";
                    break;
                default:
                    throw new ArgumentException("unknown check id " + checkId);
            }
            return (Score(inputs), inputs, plan, rc);
        }
    }

    public static class Ordering
    {
        /// <summary>Canonical §8 sort: severity band → area → check_id → anchor.</summary>
        public static List<FindingRecord> CanonicalSort(IEnumerable<FindingRecord> rows) =>
            rows.OrderBy(r => r.Band)
                .ThenBy(r => r.Area, StringComparer.Ordinal)
                .ThenBy(r => r.CheckId, StringComparer.Ordinal)
                .ThenBy(r => r.Anchor, StringComparer.Ordinal)
                .ToList();

        /// <summary>
        /// §5 fix_order_rank over SCORED findings: group by root_cause; order groups by
        /// max severity then root_cause id; within a group by severity then anchor. 1-based.
        /// NOT-ASSESSED / Info records get no rank.
        /// </summary>
        public static void AssignFixOrder(List<FindingRecord> rows)
        {
            var scored = rows.Where(r => r.Severity != "Info" && r.EvidenceLevel != "NOT-ASSESSED" && r.RootCause != null).ToList();

            var groups = scored.GroupBy(r => r.RootCause!)
                .Select(g => new
                {
                    Rc = g.Key,
                    MaxBand = g.Min(r => r.Band), // lowest band number = highest severity
                    Items = g.OrderBy(r => r.Band).ThenBy(r => r.Anchor, StringComparer.Ordinal).ToList()
                })
                .OrderBy(g => g.MaxBand)
                .ThenBy(g => g.Rc, StringComparer.Ordinal)
                .ToList();

            int rank = 1;
            foreach (var g in groups)
                foreach (var r in g.Items)
                    r.FixOrderRank = rank++;
        }
    }
}
