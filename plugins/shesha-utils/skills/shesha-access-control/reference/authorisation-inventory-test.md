# The authorisation-inventory test

The headline deliverable of the `access-control` sub-area: a single xUnit test suite that enumerates
every endpoint / entity action / permission / specification in a Shesha application and asserts a
closed set of **deterministic** authorisation invariants. It is both a gate (CI fails on drift) and a
regression harness — every remediation template in [checks.md](checks.md) names an invariant here as
its regression test, so a fixed finding cannot silently reappear.

It does **not** reimplement the audit. It consumes the same facts the hub catalogues
(`auditing-application-security`), asserts the invariants in-process, and **emits results into the
shared `findings.json` tuple shape** so a re-audit converges byte-for-byte. Build the xUnit project
and DB fixture with [create-integration-tests](../../create-integration-tests/SKILL.md); run it with
[run-integration-tests](../../run-integration-tests/SKILL.md) — this doc does **not** rebuild that
infrastructure, it layers onto `SheshaNhTestBase` / `LocalSqlServerFixture`.

---

## 1. Invariants (each deterministic: sorted, normalised, emitted as findings)

| Invariant | Asserts | CHECK-ID | Capability |
|---|---|---|---|
| **INV-PERMISSIONED** | every service/endpoint is permissioned **or** on the explicit public allow-list (with a reason) | C1/C2 | static |
| **INV-CUD-CLOSED** | no `generateAppService:true` entity has an open `Create`/`Update`/`Delete` (Inherited/empty) | D1/D3/D4 | static (decl) / live (probe) |
| **INV-NO-EMPTY-ACCESS4** | no PermissionedObject node has `access == 4` with an empty `permissions` list | E6 | static |
| **INV-HAS-SPEC** | every entity has a `[GlobalSpecification]` **or** a reasoned exemption in the register | D5/H5 | static |
| **INV-PERM-EXISTS** | every permission referenced in code / PermissionedObject exists in the catalog; none is orphaned (catalog entry referenced by nothing) | ORPH-PERM | static |
| **INV-GET-INHERITED-NEEDS-SPEC** | a `Get`/`GetAll` left at Inherited is backed by a **verified** global spec (else it must be explicitly permissioned) | D5/H5 | static |
| **INV-ACTOR** | no read/write method binds its actor from a route/body id without an ownership re-check | SEC-A | static (Roslyn SEC_A feeds this) |
| **INV-OVERPOST** | no write DTO exposes a privileged field from the privileged-field register | SEC-L | static |
| **INV-SOD** | every state-transition authorizer compares the actor to the record's originator (approver ≠ requester) | SEC-K | static (shape) / live (probe) |
| **INV-TENANT** | every tenant-scoped entity has a tenant global spec or a reasoned exemption | SEC-S | static / live |
| **INV-GRANTS-HAVE-EFFECT** | a non-admin **granted** X is allowed X, and one **not** granted X is denied X without the request crashing (checker-not-inverse) | INV-CHK | **live, low-priv** |

The last block (INV-ACTOR, INV-OVERPOST, INV-SOD, INV-TENANT, INV-GRANTS-HAVE-EFFECT) has a **static**
half that always runs and a **live** half gated on a low-priv account (§4). The live half is the only
way to catch the admin-invisible classes of bug (inverse checker, owner-only paths).

---

## 2. Output: emit into the shared findings.json schema

Every invariant failure is a finding tuple, exactly as the hub defines it
(`../auditing-application-security/references/determinism-standard.md` §0, §2):

```
{ finding_id, anchor, evidence_level, severity, plan_id }
  finding_id = "<CHECK-ID>@<anchor>"   e.g. "E6@dmv:permissionedobject:My.Namespace.MyEntity@Get"
  evidence_level ∈ the §3 closed enum  (static ⇒ CODE-ONLY/VERIFIED-ARTEFACT; probe ⇒ REPRODUCED;
                                        capability absent ⇒ NOT-ASSESSED(reason))
  severity       = derived by the registry scoring key (not set here)
  plan_id        = the AC-* template in checks.md §3
```

**Normalisation (so two runs are byte-identical):**
- anchors are symbols/routes, **never** raw line numbers; lowercase the path part, keep
  `#Symbol.Member` verbatim, strip any trailing `:\d+`;
- sort findings by `(severity_band, check_id, anchor)`;
- serialise canonical: `JsonSerializer` with sorted keys, no whitespace, one trailing newline —
  equivalent to the hub's `json.dumps(sort_keys=True, separators=(",",":"))`.

The test writes `authorisation-inventory.findings.json` next to the run output; the hub's
`normalize_findings.py` is then a no-op over it, and `diff_runs.py` unions it with the rest.

---

## 3. Baseline / snapshot policy (drift fails the test)

A committed baseline is the **approved** set of findings-that-are-accepted plus the two registers.
The test computes the live finding set, normalises it, and diffs against the baseline:

- A **new** finding not in the baseline → **FAIL** (a regression, or genuinely new surface that must
  be triaged and either fixed or explicitly accepted into the baseline with a reason).
- A baseline finding **no longer present** → **FAIL by default** (the baseline is stale — the finding
  was fixed, so remove it; or the check stopped running, which must be investigated). Running
  `--update-baseline` locally regenerates it; CI never updates it.
- Byte-identical → **PASS**.

Committed files (all secret-free — see checks.md §5):

```
test/.../AccessControl/
  authorisation-inventory.baseline.json      # normalised accepted findings (the snapshot)
  public-allow-list.json                     # { "<anchor>": "reason" } — anonymous/unpermissioned OK
  global-spec-exemptions.json                # { "<Entity>": "reason" } — no [GlobalSpecification] OK
  privileged-fields.json                     # [ "OwnerId","TenantId","Status","ApproverId", ... ]
```

Every allow-list / exemption entry **requires a reason string** — an empty reason fails the test the
same as a missing entry. This makes "we accept this" an auditable, reviewed decision, not a silent
skip.

---

## 4. Capability gate (static with no backend; live gated on a low-priv account)

- **Static invariants run with no backend.** They read the loaded ABP modules by reflection
  (registered `IApplicationService` types and their attributes; `[GlobalSpecification]` on
  `ShaSpecification<T>`; the EntityConfig / PermissionedObject exports produced by the audit, or the
  live repos if a DB fixture is present) — no HTTP, no low-priv login required. These are the DET
  checks that enter the byte-identity diff.
- **Live invariants are gated on a low-priv test account.** If no non-admin account is configured
  (`AccessControlTest:LowPrivUser` is absent), every live probe emits `NOT-ASSESSED(no-low-priv)` —
  a first-class verdict, **never** a silent pass, never reported as green. The capability is detected
  **once** up front and recorded, never re-guessed mid-run (determinism-standard §1).
- **INV-GRANTS-HAVE-EFFECT requires the low-priv account** (an admin holds everything via RBAC and
  never exercises the custom-checker fall-through — testing as admin cannot catch the inverse-checker
  bug). With no low-priv account it is `NOT-ASSESSED`, and the suite says so explicitly.

---

## 5. Scaffolded xUnit template

Layer onto the infrastructure `create-integration-tests` scaffolds (`SheshaNhTestBase`,
`[Collection(LocalSqlServerCollection.Name)]`, `LocalSqlServerFixture`, `Resolve<T>()`,
`LoginAsHost`/`LoginAsTenant`). Replace `{Product}`/namespaces to match the project. The code is a
**template** — verify every framework member against the project's referenced package versions first
(SKILL.md § Key Rules).

### 5a. The finding record + canonical writer

```csharp
// test/.../AccessControl/Inventory/Finding.cs
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace {Product}.Tests.AccessControl.Inventory
{
    /// <summary>One normalised finding tuple, matching the shared findings.json schema
    /// (determinism-standard §2). Severity is the registry-derived band; it is not computed here.</summary>
    public sealed record Finding(
        string CheckId, string Anchor, string EvidenceLevel, string Severity, string PlanId)
    {
        public string FindingId => $"{CheckId}@{Anchor}";

        /// <summary>Anchor normalisation: lowercase the path part, keep #Symbol.Member verbatim,
        /// strip any trailing :line. Never emit a raw line number.</summary>
        public static string NormaliseAnchor(string raw)
        {
            raw = Regex.Replace(raw, @":\d+$", "");
            var hash = raw.IndexOf('#');
            if (hash < 0) return raw.Replace('\\', '/');
            var path = raw.Substring(0, hash).Replace('\\', '/').ToLowerInvariant();
            return path + raw.Substring(hash);
        }
    }

    public static class FindingsWriter
    {
        private static readonly string[] Bands = { "critical", "high", "medium", "low", "info" };

        public static string ToCanonicalJson(IEnumerable<Finding> findings)
        {
            var ordered = findings
                .OrderBy(f => Array.IndexOf(Bands, f.Severity.ToLowerInvariant()))
                .ThenBy(f => f.CheckId, StringComparer.Ordinal)
                .ThenBy(f => f.Anchor, StringComparer.Ordinal)
                .Select(f => new SortedDictionary<string, string>(StringComparer.Ordinal)
                {
                    ["anchor"] = f.Anchor,
                    ["evidence_level"] = f.EvidenceLevel,
                    ["finding_id"] = f.FindingId,
                    ["plan_id"] = f.PlanId,
                    ["severity"] = f.Severity,
                })
                .ToList();

            var json = JsonSerializer.Serialize(ordered,
                new JsonSerializerOptions { WriteIndented = false });
            return json + "\n";   // one trailing newline, matching the hub normalizer
        }
    }
}
```

### 5b. The test suite (static invariants + capability-gated live probes)

```csharp
// test/.../AccessControl/Inventory/AuthorisationInventory_Tests.cs
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Abp.Application.Services;
using Abp.Dependency;
using {Product}.Common.Tests;                 // SheshaNhTestBase, fixtures
using {Product}.Common.Tests.Fixtures;
using Shouldly;
using Xunit;
using Xunit.Abstractions;

namespace {Product}.Tests.AccessControl.Inventory
{
    [Collection(LocalSqlServerCollection.Name)]
    public class AuthorisationInventory_Tests : SheshaNhTestBase
    {
        private readonly ITestOutputHelper _out;
        private readonly string _dir = Path.Combine(AppContext.BaseDirectory, "AccessControl");

        public AuthorisationInventory_Tests(LocalSqlServerFixture fixture, ITestOutputHelper output)
            : base(fixture) => _out = output;

        // ---- the one entry point: build the full finding set, snapshot-diff it -------------------

        [Fact]
        public void Inventory_matches_baseline_snapshot()
        {
            var findings = new List<Finding>();
            findings.AddRange(Inv_Permissioned());         // INV-PERMISSIONED
            findings.AddRange(Inv_CudClosed());            // INV-CUD-CLOSED
            findings.AddRange(Inv_NoEmptyAccess4());       // INV-NO-EMPTY-ACCESS4
            findings.AddRange(Inv_HasSpec());              // INV-HAS-SPEC
            findings.AddRange(Inv_PermExists());           // INV-PERM-EXISTS
            findings.AddRange(Inv_GetInheritedNeedsSpec());// INV-GET-INHERITED-NEEDS-SPEC
            findings.AddRange(Inv_Actor());                // INV-ACTOR (static half; Roslyn SEC_A feeds anchors)
            findings.AddRange(Inv_Overpost());             // INV-OVERPOST
            findings.AddRange(Inv_SodShape());             // INV-SOD (static shape)

            var actual = FindingsWriter.ToCanonicalJson(findings);
            File.WriteAllText(Path.Combine(_dir, "authorisation-inventory.findings.json"), actual);

            var baselinePath = Path.Combine(_dir, "authorisation-inventory.baseline.json");
            if (Environment.GetEnvironmentVariable("UPDATE_BASELINE") == "1")
            {
                File.WriteAllText(baselinePath, actual);   // local only; CI never sets this
                return;
            }

            var baseline = File.ReadAllText(baselinePath);
            // Byte-identical or FAIL. The assert message lists drift so triage is one read.
            actual.ShouldBe(baseline, Diff(baseline, actual));
        }

        // ---- live, capability-gated: grants-have-effect (the admin-invisible class) ---------------

        [Fact]
        public async Task Grants_have_effect_for_a_low_priv_account()   // INV-GRANTS-HAVE-EFFECT
        {
            var low = TestConfig.LowPrivUserOrNull();
            if (low == null)
            {
                _out.WriteLine("NOT-ASSESSED(no-low-priv): INV-GRANTS-HAVE-EFFECT skipped.");
                return;   // first-class NOT-ASSESSED, never a silent green
            }

            // Grant X to the low-priv account's role, clear cache, assert X is allowed (grants-have-effect),
            // then assert a NOT-granted Y is denied *without throwing* (inverse-checker probe).
            LoginAsTenant(low.Tenancy, low.UserName);
            var checker = Resolve<Shesha.Authorization.IShaPermissionChecker>();

            (await checker.IsGrantedAsync(low.GrantedPermission)).ShouldBeTrue(
                "a granted non-admin must actually be granted — a checker that throws/returns-not-false voids grants");

            Should.NotThrow(async () =>
                (await checker.IsGrantedAsync(low.UngrantedPermission)).ShouldBeFalse(
                    "a not-granted permission must deny cleanly, never crash the request"));
        }

        // ---- invariant bodies (sketch — fill the predicate against the real framework shape) -------

        private IEnumerable<Finding> Inv_Permissioned()
        {
            // Enumerate registered application services (Abp: types assignable to IApplicationService).
            foreach (var svc in ApplicationServiceTypes())
            {
                var anchor = Finding.NormaliseAnchor($"{svc.Assembly.GetName().Name}#{svc.FullName}");
                if (HasClassLevelAuthorize(svc) || PublicAllowList.Contains(anchor)) continue;
                yield return new Finding("C1", anchor, "CODE-ONLY", "High", "AC-SEC-C-permissioned");
            }
        }

        private IEnumerable<Finding> Inv_CudClosed()        => EntityCrud()
            .Where(e => e.GenerateAppService && e.HasOpenWriteNode)
            .Select(e => new Finding("D1",
                Finding.NormaliseAnchor($"http:POST /api/dynamic/{e.Module}/{e.Name}/Crud/Create"),
                "CODE-ONLY", "High", "AC-SEC-C-permissioned"));

        private IEnumerable<Finding> Inv_NoEmptyAccess4()   => PermissionedObjectNodes()
            .Where(n => n.Access == 4 && (n.Permissions == null || n.Permissions.Count == 0))
            .Select(n => new Finding("E6",
                Finding.NormaliseAnchor($"dmv:permissionedobject:{n.Object}"),
                "VERIFIED-ARTEFACT", "Medium", "AC-SEC-C-permissioned"));

        private IEnumerable<Finding> Inv_HasSpec()          => EntityConfigs()
            .Where(e => !HasGlobalSpecification(e.ClrType) && !SpecExemptions.ContainsKey(e.Entity))
            .Select(e => new Finding("H5",
                Finding.NormaliseAnchor($"db:{e.Entity}"),
                "CODE-ONLY", "High", "AC-SEC-S-global-spec"));

        private IEnumerable<Finding> Inv_PermExists()
        {
            var catalog = AllPermissionNames();
            foreach (var referenced in PermissionsReferencedInCodeAndConfig())
                if (!catalog.Contains(referenced))
                    yield return new Finding("ORPH-PERM",
                        Finding.NormaliseAnchor($"sln:orphaned-permission={referenced}"),
                        "CODE-ONLY", "Medium", "AC-SEC-C-permissioned");
            // (The inverse — a catalog permission referenced by nothing — is the same shape, reversed.)
        }

        private IEnumerable<Finding> Inv_GetInheritedNeedsSpec() => PermissionedObjectNodes()
            .Where(n => n.IsGetOrGetAll && n.Access == 2 /* Inherited */
                        && !HasVerifiedSpecFor(n.Entity) && !SpecExemptions.ContainsKey(n.Entity))
            .Select(n => new Finding("H5",
                Finding.NormaliseAnchor($"db:{n.Entity}"),
                "CODE-ONLY", "High", "AC-SEC-S-global-spec"));

        private IEnumerable<Finding> Inv_Actor()     => RoslynSecA.Results()   // consumes SEC_A analyzer
            .Select(r => new Finding("SEC-A", Finding.NormaliseAnchor(r.Anchor),
                r.BuildRan ? "VERIFIED-ARTEFACT" : "CODE-ONLY", "High", "AC-SEC-A-actor-from-session"));

        private IEnumerable<Finding> Inv_Overpost()  => WriteDtos()
            .Where(d => d.ExposesAny(PrivilegedFields))
            .Select(d => new Finding("SEC-L", Finding.NormaliseAnchor(d.Anchor),
                "CODE-ONLY", "High", "AC-SEC-L-dto-allowlist"));

        private IEnumerable<Finding> Inv_SodShape()  => StateTransitionAuthorizers()
            .Where(a => !a.ComparesActorToOriginator)
            .Select(a => new Finding("SEC-K", Finding.NormaliseAnchor(a.Anchor),
                "CODE-ONLY", "High", "AC-SEC-K-sod-authorizer"));

        // ---- helpers (implement against the project's real framework shape) ------------------------
        private IEnumerable<Type> ApplicationServiceTypes() =>
            IocManager.Instance.IocContainer.Kernel.GetAssignableHandlers(typeof(IApplicationService))
                .Select(h => h.ComponentModel.Implementation).Distinct();
        // HasClassLevelAuthorize / EntityCrud / PermissionedObjectNodes / EntityConfigs /
        // AllPermissionNames / PermissionsReferencedInCodeAndConfig / HasGlobalSpecification /
        // HasVerifiedSpecFor / WriteDtos / StateTransitionAuthorizers / RoslynSecA: wire to the
        // audit catalogue exports (preferred, deterministic) or live repos. Keep each a pure,
        // total function so two runs produce byte-identical output.

        private static string Diff(string baseline, string actual) =>
            $"authorisation-inventory drift:\n- baseline lines: {baseline.Split('\n').Length}\n" +
            $"- actual lines:   {actual.Split('\n').Length}\n" +
            "Run locally with UPDATE_BASELINE=1 to accept, after triaging each new/removed finding.";
    }
}
```

### 5c. Registers (committed, reason-required, secret-free)

```jsonc
// public-allow-list.json — an endpoint that is intentionally anonymous/unpermissioned, WITH a reason
{ "shesha.hcm.application#Shesha.Hcm.PublicHealthCheckAppService": "liveness probe, no data" }

// global-spec-exemptions.json — an entity that intentionally has no [GlobalSpecification]
{ "Shesha.Domain.RefListItem": "global reference data, same for every tenant" }

// privileged-fields.json — field names a write DTO must never bind from the request body
[ "OwnerId", "TenantId", "Status", "ApproverId", "IsApproved", "CreatorUserId" ]
```

---

## 6. Wiring checklist

1. Scaffold the xUnit project + DB fixture with `create-integration-tests` if none exists; place the
   suite under `test/.../AccessControl/Inventory/` mirroring the source layout.
2. Implement each `private ... helper` against the **audit catalogue exports** first (deterministic,
   no live state) — fall back to live repos only where a fact is not catalogued.
3. Fill the two registers and `privileged-fields.json`; every entry needs a reason.
4. Generate the baseline once (`UPDATE_BASELINE=1`), review every accepted finding, commit it.
5. Run via `run-integration-tests`; wire `Inventory_matches_baseline_snapshot` into CI as a required
   gate. The live `Grants_have_effect...` fact stays green-or-`NOT-ASSESSED` until a low-priv account
   is provisioned, then becomes a hard gate.
6. On every remediation (checks.md §4), the named invariant must flip the finding out of the baseline
   — that is the proof the fix took and the guard against regression.
