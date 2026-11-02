using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Serialization;

namespace BoxfusionTlc.SecDriver
{
    /// <summary>
    /// A single operating-standard.md §8 findings.json record. Property order here IS the
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

    /// <summary>Fixed, per-check severity inputs (checks/security.md SEC-A + R6 table).</summary>
    public static class CheckProfiles
    {
        public static readonly Dictionary<string, int> Band = new()
        {
            ["Critical"] = 0, ["High"] = 1, ["Medium"] = 2, ["Low"] = 3, ["Info"] = 4,
        };

        public static (string sev, SeverityInputs inputs, string plan, string rc) Profile(string checkId) => checkId switch
        {
            "SEC-A" => ("Critical",
                new SeverityInputs { ImpactClass = "auth_bypass", Reachability = "any_authenticated", DataSensitivity = "business" },
                "PLAN-SEC-A", "RC-no-authz-model"),
            "SEC-H" => ("High",
                new SeverityInputs { ImpactClass = "data_exposure_pii", Reachability = "low_priv", DataSensitivity = "pii_basic" },
                "PLAN-SEC-H", "RC-pii-handling"),
            _ => throw new ArgumentException("unknown check id " + checkId),
        };
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
        /// §6 fix_order_rank over SCORED findings: group by root_cause; order groups by
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
