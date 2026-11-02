using System;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Boxfusion.SecAnalyzers;
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.Diagnostics;
using Microsoft.CodeAnalysis.MSBuild;

namespace Boxfusion.SecDriver
{
    /// <summary>
    /// Runs the SEC-A and SEC-H DiagnosticAnalyzers against a target solution and emits a
    /// determinism-standard.md §8 findings.json fragment. Deterministic: anchors come from
    /// symbols, output is canonically sorted, no line numbers / timestamps / machine paths
    /// leak.
    ///
    /// Usage:
    ///   Boxfusion.SecDriver --solution &lt;path.sln&gt; --repo-root &lt;dir&gt; --out &lt;findings.json&gt; [--commit &lt;sha&gt;]
    /// </summary>
    internal static class Program
    {
        private static async Task<int> Main(string[] rawArgs)
        {
            var args = ParseArgs(rawArgs);
            if (!args.TryGetValue("solution", out var sln) || !args.TryGetValue("out", out var outPath))
            {
                Console.Error.WriteLine("usage: --solution <sln> --repo-root <dir> --out <findings.json> [--commit <sha>]");
                return 2;
            }
            string repoRoot = args.TryGetValue("repo-root", out var rr) ? rr : Path.GetDirectoryName(Path.GetFullPath(sln))!;
            repoRoot = Path.GetFullPath(repoRoot);
            string? commit = args.TryGetValue("commit", out var c) ? c : null;

            if (!MSBuildLocator.IsRegistered)
                MSBuildLocator.RegisterDefaults();

            List<FindingRecord> records;
            try
            {
                records = await AnalyzeAsync(sln, repoRoot, commit);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("analyzer could not obtain a compilation: " + ex.Message);
                records = Fallback(commit);
            }

            var sorted = Ordering.CanonicalSort(records);
            Ordering.AssignFixOrder(sorted);

            var json = JsonSerializer.Serialize(sorted, new JsonSerializerOptions
            {
                WriteIndented = true,
                DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.Never,
            });
            // stable newline so byte-compare is portable
            json = json.Replace("\r\n", "\n");
            File.WriteAllText(outPath, json + "\n");
            Console.Error.WriteLine($"wrote {sorted.Count} record(s) to {outPath}");
            foreach (var r in sorted)
                Console.Error.WriteLine($"  {r.Severity,-8} {r.EvidenceLevel,-18} {r.FindingId}");
            return 0;
        }

        private static async Task<List<FindingRecord>> AnalyzeAsync(string sln, string repoRoot, string? commit)
        {
            // Disable NuGetAudit (it tries to reach the machine's private Shesha feed for
            // vulnerability data and fails the design-time build) and warnings-as-errors, so
            // every project yields a Compilation from the already-restored references.
            var props = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["NuGetAudit"] = "false",
                ["RunNuGetAudit"] = "false",
                ["TreatWarningsAsErrors"] = "false",
                ["RestorePackagesWithLockFile"] = "false",
            };
            using var ws = MSBuildWorkspace.Create(props);
            ws.WorkspaceFailed += (_, e) =>
            {
                if (e.Diagnostic.Kind == WorkspaceDiagnosticKind.Failure)
                    Console.Error.WriteLine("  [workspace] " + e.Diagnostic.Message);
            };

            var solution = await ws.OpenSolutionAsync(sln);
            var analyzers = ImmutableArray.Create<DiagnosticAnalyzer>(
                new SecABrowserTrustedAnalyzer(), new SecHPiiInLogsAnalyzer());

            // collapse by finding_id; carry multiplicity in sources[]
            var byId = new Dictionary<string, FindingRecord>(StringComparer.Ordinal);

            // deterministic project order
            int loaded = 0, skipped = 0;
            foreach (var project in solution.Projects.OrderBy(p => p.FilePath, StringComparer.Ordinal))
            {
                if (project.Language != LanguageNames.CSharp) continue;
                var compilation = await project.GetCompilationAsync();
                if (compilation == null) { skipped++; Console.Error.WriteLine("  [no-compilation] " + project.Name); continue; }
                loaded++;

                var withAnalyzers = compilation.WithAnalyzers(analyzers,
                    new CompilationWithAnalyzersOptions(
                        options: project.AnalyzerOptions,
                        onAnalyzerException: (ex, analyzer, diag) =>
                            Console.Error.WriteLine($"  [analyzer-crash] {analyzer}: {ex.Message}"),
                        concurrentAnalysis: false,
                        logAnalyzerExecutionTime: false));

                var diags = await withAnalyzers.GetAnalyzerDiagnosticsAsync();
                foreach (var d in diags)
                {
                    if (d.Id != SecABrowserTrustedAnalyzer.Id && d.Id != SecHPiiInLogsAnalyzer.Id) continue;
                    AddFinding(byId, d, repoRoot, commit);
                }
            }

            Console.Error.WriteLine($"  projects: {loaded} compiled, {skipped} skipped");
            if (loaded == 0) throw new InvalidOperationException("no C# project produced a Compilation");
            return byId.Values.ToList();
        }

        private static void AddFinding(Dictionary<string, FindingRecord> byId, Diagnostic d, string repoRoot, string? commit)
        {
            d.Properties.TryGetValue(AnchorHelper.AnchorKey, out var fragment);
            d.Properties.TryGetValue(AnchorHelper.PathKey, out var absPath);
            if (string.IsNullOrEmpty(fragment) || string.IsNullOrEmpty(absPath)) return;

            string checkId = d.Id.Replace('_', '-');      // SEC_A → SEC-A (Roslyn id → check-registry check id)
            string rel = NormalizePath(repoRoot, absPath!);
            string anchor = rel + fragment;               // path lower-cased; #Type.Member verbatim (§2)
            string findingId = checkId + "@" + anchor;

            if (byId.TryGetValue(findingId, out var existing))
            {
                if (!existing.Sources.Contains(rel)) existing.Sources.Add(rel);
                return;
            }

            var (sev, inputs, plan, rc) = CheckProfiles.Profile(checkId);
            byId[findingId] = new FindingRecord
            {
                FindingId = findingId,
                CheckId = checkId,
                Area = "security",
                Anchor = anchor,
                EvidenceLevel = "VERIFIED-ARTEFACT",
                ExecutionClass = "roslyn-analyzer-scan",
                Severity = sev,
                Band = CheckProfiles.Band[sev],
                SeverityInputs = inputs,
                PlanId = plan,
                RootCause = rc,
                FixOrderRank = null,
                Sources = new List<string> { rel },
                NotAssessedReason = null,
                NonDeterministic = false,
                CommitSha = commit,
            };
        }

        /// <summary>§2 path normalization: repo-root-relative → '/' → lower-cased path part.</summary>
        private static string NormalizePath(string repoRoot, string abs)
        {
            string full = Path.GetFullPath(abs);
            string rootFull = repoRoot.TrimEnd('\\', '/');
            string rel = full.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase)
                ? full.Substring(rootFull.Length).TrimStart('\\', '/')
                : full;
            return rel.Replace('\\', '/').ToLowerInvariant();
        }

        /// <summary>Honest NOT-ASSESSED(no-build) fallback — never a silent empty pass.</summary>
        private static List<FindingRecord> Fallback(string? commit)
        {
            FindingRecord Na(string checkId) => new()
            {
                FindingId = checkId + "@analyzer",
                CheckId = checkId,
                Area = "security",
                Anchor = "analyzer",
                EvidenceLevel = "NOT-ASSESSED(no-build)",
                ExecutionClass = "roslyn-analyzer-scan",
                Severity = "Info",
                Band = CheckProfiles.Band["Info"],
                SeverityInputs = null,
                PlanId = null,
                RootCause = null,
                FixOrderRank = null,
                Sources = new List<string>(),
                NotAssessedReason = "no-build",
                NonDeterministic = false,
                CommitSha = commit,
            };
            return new List<FindingRecord> { Na("SEC-A"), Na("SEC-H") };
        }

        private static Dictionary<string, string> ParseArgs(string[] a)
        {
            var d = new Dictionary<string, string>(StringComparer.Ordinal);
            for (int i = 0; i < a.Length - 1; i++)
                if (a[i].StartsWith("--")) d[a[i].Substring(2)] = a[++i];
            return d;
        }
    }
}
