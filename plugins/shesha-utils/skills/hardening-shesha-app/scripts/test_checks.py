"""Fixture tests for the hardening checks. Run: python scripts/test_checks.py

Each test builds a throwaway repository, scans it, applies the fix in memory, and re-scans.
Add a test here for every new check (see references/adding-a-check.md).
"""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import (NotFixable, Repo, Status, diff, load_checks, score_severity,  # noqa: E402
                  secret_fingerprint, SEVERITY_BANDS)
from checks.token_blacklist import framework_supports  # noqa: E402
import harden  # noqa: E402
import normalize_findings  # noqa: E402
import diff_runs  # noqa: E402

REGISTRY = load_checks()

PROPS = "<Project><PropertyGroup><SheshaVersion>{v}</SheshaVersion></PropertyGroup></Project>"

WEB_CORE = """\
using System;
using Microsoft.Extensions.Configuration;

namespace Demo.Web.Core
{
    public class DemoWebCoreModule
    {
        private readonly IConfigurationRoot _appConfiguration;

        private void ConfigureTokenAuth()
        {
            var tokenAuthConfig = IocManager.Resolve<TokenAuthConfiguration>();
            tokenAuthConfig.Issuer = _appConfiguration["Authentication:JwtBearer:Issuer"];
            tokenAuthConfig.Expiration = TimeSpan.FromDays(5);
        }
    }
}
"""

AUTH_WITH_EVENTS = """\
using System;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Shesha;

namespace Demo.Web.Host.Startup
{
    public static class AuthConfigurer
    {
        public static void Configure(IServiceCollection services, IConfiguration configuration)
        {
            services.AddAuthentication().AddJwtBearer("JwtBearer", options =>
            {
                options.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidateLifetime = true,
                };

                options.Events = new JwtBearerEvents
                {
                    OnMessageReceived = QueryStringTokenResolver
                };
            });
        }
    }
}
"""

AUTH_NO_EVENTS = """\
using System;

namespace Demo.Web.Host.Startup
{
    public static class AuthConfigurer
    {
        public static void Configure(IServiceCollection services)
        {
            services.AddAuthentication().AddJwtBearer("JwtBearer", o =>
            {
                o.TokenValidationParameters = new TokenValidationParameters
                {
                    // "}" inside a comment and a string must not confuse brace matching
                    ValidIssuer = "}",
                };
            });
        }
    }
}
"""

AUTH_CUSTOM_HANDLER = AUTH_WITH_EVENTS.replace(
    "OnMessageReceived = QueryStringTokenResolver",
    "OnTokenValidated = async ctx => { await Task.CompletedTask; }")


class RepoCase(unittest.TestCase):
    version = "0.43.37"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.put("backend/Directory.Build.props", PROPS.format(v=self.version))

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel: str, text: str, raw: bytes | None = None) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw if raw is not None else textwrap.dedent(text).encode())
        return path

    def run_check(self, check_id: str, **opts):
        """Scan, fix (in memory), re-scan. Returns (before, edits, after, repo)."""
        repo = Repo(self.root)
        check = REGISTRY[check_id](opts)
        before = check.scan(repo)
        edits = check.fix(repo, before) if before.fixable else []
        for e in edits:
            repo.stage(e)
        after = check.scan(repo)
        return before, edits, after, repo


class TokenLifetimeTests(RepoCase):
    def test_hard_coded_days_is_rewritten_to_configurable_minutes(self):
        self.put("backend/src/Web.Core/DemoWebCoreModule.cs", WEB_CORE)
        before, edits, after, _ = self.run_check("token-lifetime")
        self.assertEqual(before.status, Status.FAIL)
        self.assertIn('_appConfiguration["Authentication:JwtBearer:TokenLifetimeMinutes"]', edits[0].new_text)
        self.assertIn(": 120);", edits[0].new_text)
        self.assertEqual(after.status, Status.PASS)

    def test_minutes_option_and_no_config_variable(self):
        self.put("backend/src/Web.Core/M.cs", WEB_CORE.replace(
            '            tokenAuthConfig.Issuer = _appConfiguration["Authentication:JwtBearer:Issuer"];\n', ""))
        _, edits, after, _ = self.run_check("token-lifetime", minutes=60)
        self.assertIn("tokenAuthConfig.Expiration = TimeSpan.FromMinutes(60);", edits[0].new_text)
        self.assertEqual(after.status, Status.PASS)

    def test_warn_band(self):
        self.put("backend/src/Web.Core/M.cs", WEB_CORE.replace("FromDays(5)", "FromHours(12)"))
        before, _, _, _ = self.run_check("token-lifetime")
        self.assertEqual(before.status, Status.WARN)

    def test_short_lifetime_passes(self):
        self.put("backend/src/Web.Core/M.cs", WEB_CORE.replace("FromDays(5)", "FromHours(2)"))
        before, edits, _, _ = self.run_check("token-lifetime")
        self.assertEqual(before.status, Status.PASS)
        self.assertEqual(edits, [])

    def test_config_driven_value_in_appsettings_is_rewritten(self):
        self.put("backend/src/Web.Core/M.cs", WEB_CORE.replace(
            "TimeSpan.FromDays(5)", 'TimeSpan.Parse(_appConfiguration["Authentication:JwtBearer:ExpireTimeSpan"])'))
        self.put("backend/src/Web.Host/appsettings.json",
                 '{\n  // comment\n  "Authentication": { "JwtBearer": { "ExpireTimeSpan": "5.00:00:00" } }\n}\n')
        before, edits, after, _ = self.run_check("token-lifetime")
        self.assertEqual(before.status, Status.FAIL)
        self.assertIn('"ExpireTimeSpan": "02:00:00"', edits[0].new_text)
        self.assertIn("// comment", edits[0].new_text)
        self.assertEqual(after.status, Status.PASS)

    def test_missing_assignment_is_manual(self):
        self.put("backend/src/Web.Core/M.cs", "class TokenAuthConfiguration {}")
        before, _, _, _ = self.run_check("token-lifetime")
        self.assertEqual(before.status, Status.MANUAL)


class TokenBlacklistTests(RepoCase):
    def test_adds_handler_to_existing_events(self):
        self.put("backend/src/Web.Host/Startup/AuthConfigurer.cs", AUTH_WITH_EVENTS)
        before, edits, after, _ = self.run_check("token-blacklist")
        self.assertEqual(before.status, Status.FAIL)
        text = edits[0].new_text
        self.assertIn("                    OnTokenValidated = context => context.EnsureTokenIsNotBlacklistedAsync(),\n"
                      "                    OnMessageReceived = QueryStringTokenResolver", text)
        self.assertIn("using Shesha.Authentication.JwtBearer;\n", text)
        self.assertEqual(after.status, Status.PASS)

    def test_adds_events_block_when_missing(self):
        self.put("backend/src/Web.Host/Startup/AuthConfigurer.cs", AUTH_NO_EVENTS)
        _, edits, after, _ = self.run_check("token-blacklist")
        text = edits[0].new_text
        self.assertIn("o.Events = new JwtBearerEvents", text)
        self.assertIn("using Microsoft.AspNetCore.Authentication.JwtBearer;", text)
        self.assertLess(text.index('ValidIssuer = "}"'), text.index("o.Events"))
        self.assertEqual(after.status, Status.PASS)

    def test_custom_handler_is_reported_not_rewritten(self):
        self.put("backend/src/Web.Host/Startup/AuthConfigurer.cs", AUTH_CUSTOM_HANDLER)
        before, edits, _, _ = self.run_check("token-blacklist")
        self.assertEqual(before.status, Status.FAIL)
        self.assertFalse(before.fixable)
        self.assertEqual(edits, [])

    def test_crlf_and_bom_are_preserved(self):
        crlf = textwrap.dedent(AUTH_WITH_EVENTS).replace("\n", "\r\n").encode()
        path = self.put("backend/src/Web.Host/Startup/AuthConfigurer.cs", "", raw=b"\xef\xbb\xbf" + crlf)
        repo = Repo(self.root)
        check = REGISTRY["token-blacklist"]()
        edit = check.fix(repo, check.scan(repo))[0]
        repo.write(edit)
        data = path.read_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_version_rule(self):
        self.assertFalse(framework_supports("0.43.17"))
        self.assertTrue(framework_supports("0.43.19"))
        self.assertFalse(framework_supports("0.44.2"))
        self.assertTrue(framework_supports("0.45.0"))
        self.assertIsNone(framework_supports(None))

    def test_restored_package_detection(self):
        """Uses the real NuGet cache; skipped for versions not restored on this machine."""
        expected = {"0.43.17": False, "0.43.19": True, "0.44.2": False, "0.45.1": True}
        for version, has in expected.items():
            if Repo(self.root).package_dll("Shesha.Application", "Shesha.Application.dll", version) is None:
                continue
            self.put("backend/Directory.Build.props", PROPS.format(v=version))
            ok, _ = REGISTRY["token-blacklist"]().applies(Repo(self.root))
            self.assertEqual(ok, has, version)


class UserLockoutTests(RepoCase):
    def test_default_passes_with_note(self):
        self.put("backend/src/A.cs", "class A {}")
        before, _, _, _ = self.run_check("user-lockout")
        self.assertEqual(before.status, Status.PASS)
        self.assertTrue(before.notes)

    def test_disabled_default_is_fixed(self):
        self.put("backend/src/M.cs", "s.UserLockOutEnabled.WithDefaultValue(false);")
        before, edits, after, _ = self.run_check("user-lockout")
        self.assertEqual(before.status, Status.FAIL)
        self.assertIn("WithDefaultValue(true)", edits[0].new_text)
        self.assertEqual(after.status, Status.PASS)

    def test_weak_values_and_bypass_are_flagged(self):
        self.put("backend/src/M.cs", "s.MaxFailedAccessAttemptsBeforeLockout.WithDefaultValue(50);\n"
                                     "s.DefaultAccountLockoutSeconds.WithDefaultValue(5);\n"
                                     "await _logInManager.LoginAsync(u, p, shouldLockout: false);\n")
        before, _, _, _ = self.run_check("user-lockout")
        statuses = sorted(i.status.value for i in before.issues)
        self.assertEqual(statuses, ["manual", "warn", "warn"])


STARTUP = """\
using Hangfire;
using Demo.Hangfire;
using Shesha.Authorization;

namespace Demo.Web.Host.Startup
{
    public class Startup
    {
        public void Configure(IApplicationBuilder app)
        {
            app.UseSwaggerUI();
            app.UseHangfireDashboard("/hangfire",
                new DashboardOptions
                {
                    Authorization = new[] { new HangfireAuthorizationFilter() }
                });
            app.UseMiddleware<GraphQLMiddleware>();
        }
    }
}
"""

APP_FILTER = """\
using Hangfire.Dashboard;
using Shesha.Authentication.JwtBearer;

namespace Demo.Hangfire
{
    /// <summary>Hangfire authorization filter</summary>
    public class HangfireAuthorizationFilter : IDashboardAuthorizationFilter
    {
        public bool Authorize(DashboardContext context)
        {
            return context.GetHttpContext().GetUsernameFromJwtToken()?.Trim().ToLower() == "admin";
        }
    }
}
"""

STARTUP_PATH = "backend/src/Demo.Web.Host/Startup/Startup.cs"
FILTER_PATH = "backend/src/Demo.Web.Core/Hangfire/HangfireAuthorizationFilter.cs"


class HangfireDashboardTests(RepoCase):
    def run_with_extension(self, available, **opts):
        with mock.patch.object(REGISTRY["hangfire-dashboard"], "extension_available",
                               staticmethod(lambda repo: available)):
            return self.run_check("hangfire-dashboard", **opts)

    def test_switches_to_extension_and_deletes_app_filter(self):
        self.put(STARTUP_PATH, STARTUP)
        self.put(FILTER_PATH, APP_FILTER)
        before, edits, after, _ = self.run_with_extension(True)
        self.assertEqual(before.status, Status.FAIL)
        self.assertTrue(before.fixable)
        startup = next(e for e in edits if e.path.name == "Startup.cs").new_text
        self.assertIn("            app.UseSheshaHangfireDashboard();\n            app.UseMiddleware", startup)
        self.assertNotIn("DashboardOptions", startup)
        self.assertIn("using Shesha.Scheduler.Extensions;\n", startup)
        self.assertNotIn("using Demo.Hangfire;", startup)
        self.assertIn("using Hangfire;\n", startup)          # still needed for AddHangfire etc.
        deleted = [e for e in edits if e.deletes]
        self.assertEqual([e.path.name for e in deleted], ["HangfireAuthorizationFilter.cs"])
        self.assertEqual(after.status, Status.PASS)

    def test_not_applied_when_version_lacks_extension(self):
        self.put(STARTUP_PATH, STARTUP)
        self.put(FILTER_PATH, APP_FILTER)
        before, edits, _, _ = self.run_with_extension(False)
        self.assertEqual(before.status, Status.FAIL)
        self.assertFalse(before.fixable)
        self.assertEqual(edits, [])
        self.assertTrue(any("run this skill again" in n and "Upgrade Shesha" in n for n in before.notes))
        with self.assertRaises(NotFixable):
            REGISTRY["hangfire-dashboard"]().fix(Repo(self.root), before)

    def test_unrestored_package_asks_for_restore(self):
        self.put(STARTUP_PATH, STARTUP)
        before, _, _, _ = self.run_with_extension(None)
        self.assertFalse(before.fixable)
        self.assertTrue(any("dotnet restore" in n for n in before.notes))

    def test_custom_path_and_framework_filter(self):
        self.put(STARTUP_PATH, STARTUP.replace('"/hangfire"', '"/jobs"').replace(
            "new HangfireAuthorizationFilter()", "new Shesha.Scheduler.Hangfire.HangfireAuthorizationFilter()"))
        before, edits, after, _ = self.run_with_extension(True)
        self.assertEqual(before.status, Status.FAIL)
        self.assertIn('app.UseSheshaHangfireDashboard("/jobs");', edits[0].new_text)
        self.assertEqual(after.status, Status.PASS)

    def test_custom_filter_is_left_to_a_human(self):
        self.put(STARTUP_PATH, STARTUP)
        self.put(FILTER_PATH, APP_FILTER.replace(
            'GetUsernameFromJwtToken()?.Trim().ToLower() == "admin"', "IsInOfficeNetwork()"))
        before, _, _, _ = self.run_with_extension(True)
        self.assertEqual(before.status, Status.MANUAL)
        self.assertFalse(before.fixable)

    def test_extra_dashboard_options_are_left_to_a_human(self):
        self.put(STARTUP_PATH, STARTUP.replace("{\n                    Authorization",
                                               "{\n                    DashboardTitle = \"Jobs\",\n"
                                               "                    Authorization"))
        before, _, _, _ = self.run_with_extension(True)
        self.assertEqual(before.status, Status.MANUAL)

    def test_filter_used_elsewhere_is_kept(self):
        self.put(STARTUP_PATH, STARTUP)
        self.put(FILTER_PATH, APP_FILTER)
        self.put("backend/src/Demo.Web.Core/Other.cs", "class Other { object f = new HangfireAuthorizationFilter(); }")
        _, edits, _, _ = self.run_with_extension(True)
        self.assertFalse(any(e.deletes for e in edits))
        startup = edits[0].new_text
        self.assertIn("using Demo.Hangfire;", startup)       # namespace still declared, keep the using

    def test_leftover_unused_filter_is_deleted_even_before_upgrade(self):
        self.put(STARTUP_PATH, STARTUP.replace('app.UseHangfireDashboard("/hangfire",\n'
                                               "                new DashboardOptions\n"
                                               "                {\n"
                                               "                    Authorization = new[] { new HangfireAuthorizationFilter() }\n"
                                               "                });", "app.UseSheshaHangfireDashboard();"))
        self.put(FILTER_PATH, APP_FILTER)
        before, edits, after, _ = self.run_with_extension(False)
        self.assertEqual(before.status, Status.WARN)
        self.assertTrue(any(e.deletes for e in edits))
        self.assertEqual(after.status, Status.PASS)

    def test_no_dashboard_passes(self):
        self.put("backend/src/A.cs", "class A {}")
        before, _, _, _ = self.run_with_extension(False)
        self.assertEqual(before.status, Status.PASS)

    def test_delete_is_written_to_disk(self):
        self.put(STARTUP_PATH, STARTUP)
        path = self.put(FILTER_PATH, APP_FILTER)
        repo = Repo(self.root)
        with mock.patch.object(REGISTRY["hangfire-dashboard"], "extension_available",
                               staticmethod(lambda r: True)):
            check = REGISTRY["hangfire-dashboard"]()
            for edit in check.fix(repo, check.scan(repo)):
                self.assertTrue(diff(repo, edit))
                repo.stage(edit)
                repo.write(edit)
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())              # emptied folder removed too

    def test_restored_package_detection(self):
        """Uses the real NuGet cache: no released version has the extension yet (update once #5554 ships)."""
        for version in ("0.43.37", "0.44.2", "0.45.1"):
            if Repo(self.root).package_dll("Shesha.Scheduler", "Shesha.Scheduler.dll", version) is None:
                continue
            self.put("backend/Directory.Build.props", PROPS.format(v=version))
            self.assertFalse(REGISTRY["hangfire-dashboard"].extension_available(Repo(self.root)), version)


class RunnerCommitTests(RepoCase):
    """harden.py fix --apply --commit: one commit per check, user's own edits never committed."""

    def git(self, *args, check=True) -> str:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=check).stdout

    def init_repo(self, autocrlf="false"):
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "Test")
        self.git("config", "core.autocrlf", autocrlf)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.git("checkout", "-q", "-b", "harden")

    def run_harden(self, *extra) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            try:
                code = harden.main(["fix", "--repo", str(self.root), "--only", "token-blacklist,token-lifetime",
                                    "--apply", "--commit", *extra])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()

    def setup_two_checks(self):
        self.put("backend/src/Web.Core/DemoWebCoreModule.cs", WEB_CORE)
        self.put("backend/src/Web.Host/Startup/AuthConfigurer.cs", AUTH_WITH_EVENTS)

    def test_one_commit_per_check_and_final_report(self):
        self.setup_two_checks()
        self.init_repo()
        code, out = self.run_harden("--trailer", "Co-Authored-By: Bot <bot@example.com>")
        self.assertEqual(code, 0, out)
        log = self.git("log", "--format=%s", "main..HEAD").splitlines()
        self.assertEqual(log, ["Harden token-lifetime: " + REGISTRY["token-lifetime"].title,
                               "Harden token-blacklist: " + REGISTRY["token-blacklist"].title])
        for rev, name in (("HEAD", "DemoWebCoreModule.cs"), ("HEAD~1", "AuthConfigurer.cs")):
            files = self.git("show", "--name-only", "--format=", rev).split()
            self.assertEqual([Path(f).name for f in files], [name])
        self.assertIn("Co-Authored-By: Bot <bot@example.com>", self.git("log", "-1", "--format=%B"))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertIn("| Check | Gap found | Current state | Action taken |", out)
        self.assertRegex(out, r"\| `token-blacklist` \| yes \(FAIL\) \| resolved \| fixed, committed [0-9a-f]{7,}")

    def check_users_edit_survives(self, autocrlf: str, crlf: bool):
        text = textwrap.dedent(AUTH_WITH_EVENTS)
        if crlf:
            text = text.replace("\n", "\r\n")
        self.put("backend/src/Web.Host/Startup/AuthConfigurer.cs", "", raw=text.encode())
        self.put("backend/src/Web.Core/DemoWebCoreModule.cs", WEB_CORE)
        self.init_repo(autocrlf)
        path = self.root / "backend/src/Web.Host/Startup/AuthConfigurer.cs"
        nl = "\r\n" if crlf else "\n"
        # well away from the fix's hunks (merge-file treats adjacent edits as a conflict)
        path.write_bytes(path.read_bytes() + f"// user's WIP{nl}".encode())
        code, out = self.run_harden()
        self.assertEqual(code, 0, out)
        committed = self.git("show", "HEAD~1:backend/src/Web.Host/Startup/AuthConfigurer.cs")
        self.assertIn("EnsureTokenIsNotBlacklistedAsync", committed)
        self.assertNotIn("user's WIP", committed)
        self.assertIn("user's WIP", path.read_text(encoding="utf-8"))
        self.assertIn("AuthConfigurer.cs", self.git("status", "--porcelain"))    # WIP still uncommitted
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        wip = self.git("diff", "--", "backend/src/Web.Host/Startup/AuthConfigurer.cs")
        changed = [ln.rstrip("\r") for ln in wip.splitlines() if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
        self.assertEqual(changed, ["+// user's WIP"])                             # only the WIP, no EOL churn

    def test_users_uncommitted_edit_stays_out_of_the_commit_lf(self):
        self.check_users_edit_survives("false", crlf=False)

    def test_users_uncommitted_edit_stays_out_of_the_commit_crlf_autocrlf(self):
        self.check_users_edit_survives("true", crlf=True)

    def test_overlapping_user_edit_is_not_committed(self):
        self.setup_two_checks()
        self.init_repo()
        path = self.root / "backend/src/Web.Host/Startup/AuthConfigurer.cs"
        path.write_text(path.read_text().replace("OnMessageReceived = QueryStringTokenResolver",
                                                 "OnMessageReceived = MyResolver"), encoding="utf-8")
        code, out = self.run_harden()
        self.assertIn("NOT committed", out)
        self.assertIn("EnsureTokenIsNotBlacklistedAsync", path.read_text())         # fix still applied
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")           # nothing left staged
        self.assertEqual(len(self.git("log", "--format=%s", "main..HEAD").splitlines()), 1)  # lifetime only

    def test_refuses_staged_changes_and_default_branch(self):
        self.setup_two_checks()
        self.init_repo()
        self.put("backend/src/Extra.cs", "class Extra {}")
        self.git("add", "backend/src/Extra.cs")
        code, _ = self.run_harden()
        self.assertIn("already staged", str(code))
        self.git("reset", "-q")
        self.git("checkout", "-q", "main")
        code, _ = self.run_harden()
        self.assertIn("default branch", str(code))

    def test_blocked_fix_shows_in_final_report(self):
        self.put(STARTUP_PATH, STARTUP)
        self.put(FILTER_PATH, APP_FILTER)
        self.init_repo()
        out = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch.object(
                REGISTRY["hangfire-dashboard"], "extension_available", staticmethod(lambda r: False)):
            harden.main(["fix", "--repo", str(self.root), "--only", "hangfire-dashboard", "--apply", "--commit"])
        self.assertIn("WARNING - not applied: needs a Shesha version with UseSheshaHangfireDashboard()", out.getvalue())
        self.assertRegex(out.getvalue(), r"\| `hangfire-dashboard` \| yes \(FAIL\) \| FAIL: .* \| not applied: .*re-run \|")
        self.assertEqual(self.git("log", "--format=%s", "main..HEAD"), "")


APPSETTINGS = '{{\n  // comment\n  "Authentication": {{ "JwtBearer": {{ "SecurityKey": "{key}" }} }}\n}}\n'
STARTER_KEY = "secretKey_secretKeysecretKeysecretKey"   # ABP template default; fingerprint is seeded
KEY_PATH = "backend/src/Web.Host/appsettings.json"


class JwtSigningKeyTests(RepoCase):
    def test_committed_literal_is_blanked_and_secret_not_echoed(self):
        from core import redact_secrets
        secret = "A_sufficiently_long_committed_signing_key_0001"
        self.put(KEY_PATH, APPSETTINGS.format(key=secret))
        # compute the diff on a fresh (un-staged) repo so the redaction path is exercised
        repo = Repo(self.root)
        check = REGISTRY["jwt-signing-key"]()
        before = check.scan(repo)
        edits = check.fix(repo, before)
        self.assertIn('"SecurityKey": ""', edits[0].new_text)
        self.assertIn("// comment", edits[0].new_text)                 # formatting preserved
        self.assertEqual(edits[0].redactions, (secret,))
        self.assertNotIn(secret, diff(repo, edits[0]))                 # the shown diff masks the value
        self.assertIn("redacted", redact_secrets(f"old: {secret}", edits[0].redactions))
        self.assertNotIn(secret, before.summary)                       # the report never echoes the key
        for i in before.issues:
            self.assertNotIn(secret, i.message)
        for e in edits:
            repo.stage(e)
        self.assertEqual(check.scan(repo).status, Status.PASS)

    def test_reference_and_empty_pass(self):
        self.put(KEY_PATH, APPSETTINGS.format(key=""))
        self.assertEqual(self.run_check("jwt-signing-key")[0].status, Status.PASS)
        self.put(KEY_PATH, APPSETTINGS.format(key="$(JwtSigningKey)"))
        self.assertEqual(self.run_check("jwt-signing-key")[0].status, Status.PASS)

    def test_known_starter_key_is_flagged_as_forgeable(self):
        self.put(KEY_PATH, APPSETTINGS.format(key=STARTER_KEY))
        before = self.run_check("jwt-signing-key")[0]
        self.assertEqual(before.status, Status.FAIL)
        self.assertTrue(any("starter key" in i.message for i in before.issues))
        rows = before.shared_findings(REGISTRY["jwt-signing-key"]())
        self.assertEqual(rows[0]["check_id"], "SEC-P")                 # per-issue canonical id override
        self.assertEqual(rows[0]["evidence_level"], "VERIFIED-ARTEFACT")

    def test_short_key_notes_weakness(self):
        self.put(KEY_PATH, APPSETTINGS.format(key="shortkey"))
        before = self.run_check("jwt-signing-key")[0]
        self.assertEqual(before.status, Status.FAIL)
        self.assertTrue(any("weak" in i.message for i in before.issues))


CORS_ANY = """\
using Microsoft.AspNetCore.Builder;
namespace Demo.Web.Host.Startup
{
    public class Startup
    {
        public void ConfigureServices(IServiceCollection services)
        {
            services.AddCors(o => o.AddDefaultPolicy(b => b.AllowAnyOrigin().AllowAnyHeader()));
        }
    }
}
"""
CORS_ANY_WITH_CREDS = CORS_ANY.replace("AllowAnyOrigin().AllowAnyHeader()",
                                       "AllowAnyOrigin().AllowCredentials()")
CORS_SAFE = CORS_ANY.replace("AllowAnyOrigin()", 'WithOrigins("https://app.example.com")')
CORS_PATH = "backend/src/Web.Host/Startup/Startup.cs"


class CorsOriginsTests(RepoCase):
    def test_wildcard_origin_is_flagged_a2(self):
        self.put(CORS_PATH, CORS_ANY)
        before = self.run_check("cors-origins")[0]
        self.assertEqual(before.status, Status.FAIL)
        rows = before.shared_findings(REGISTRY["cors-origins"]())
        self.assertEqual(rows[0]["check_id"], "A2")

    def test_wildcard_with_credentials_is_a3(self):
        self.put(CORS_PATH, CORS_ANY_WITH_CREDS)
        before = self.run_check("cors-origins")[0]
        self.assertEqual(before.status, Status.FAIL)
        rows = before.shared_findings(REGISTRY["cors-origins"]())
        self.assertEqual(rows[0]["check_id"], "A3")
        self.assertEqual(rows[0]["severity"], "Critical")             # A3 escalates (auth_bypass + anonymous)

    def test_appsettings_wildcard_is_b3(self):
        self.put("backend/src/Web.Host/appsettings.json",
                 '{ "App": { "CorsOrigins": "https://a.com,*" } }')
        before = self.run_check("cors-origins")[0]
        self.assertEqual(before.status, Status.FAIL)
        self.assertEqual(before.shared_findings(REGISTRY["cors-origins"]())[0]["check_id"], "B3")

    def test_concrete_origins_pass(self):
        self.put(CORS_PATH, CORS_SAFE)
        self.assertEqual(self.run_check("cors-origins")[0].status, Status.PASS)

    def test_fix_is_left_to_a_human(self):
        self.put(CORS_PATH, CORS_ANY)
        with self.assertRaises(NotFixable):
            REGISTRY["cors-origins"]().fix(Repo(self.root), self.run_check("cors-origins")[0])


FIXTURE_DOC = {
    "schema": "hardening-shesha-app/findings@1",
    "runMeta": {"repo": "/x", "commit": "abc", "generated": "2026-01-01T00:00:00Z", "mode": "scan only"},
    "capabilities": {"git": {"present": True}, "live_backend": {"present": False, "reason": "NOT-ASSESSED(no --base-url)"}},
    "findings": [
        {"finding_id": "A10@startup.cs#Startup.UseHangfireDashboard", "check_id": "A10",
         "anchor": "startup.cs#Startup.UseHangfireDashboard", "evidence_level": "CODE-ONLY",
         "severity": "Critical", "plan_id": "PLAN-hangfire", "root_cause": "RC-sec-starter-surface",
         "non_deterministic": False},
        {"finding_id": "I3@m.cs#Mod.Expiration", "check_id": "I3", "anchor": "m.cs#Mod.Expiration",
         "evidence_level": "CODE-ONLY", "severity": "High", "plan_id": "PLAN-token-lifetime",
         "root_cause": "RC-sec-token", "non_deterministic": False},
        {"finding_id": "I4@a.cs#Auth.OnTokenValidated", "check_id": "I4",
         "anchor": "a.cs#Auth.OnTokenValidated", "evidence_level": "CODE-ONLY", "severity": "High",
         "plan_id": "PLAN-token-blacklist", "root_cause": "RC-sec-token", "non_deterministic": True},
    ],
}


class ReproducibilityTests(unittest.TestCase):
    """The acceptance test (determinism-standard §0): one fixture normalised twice is byte-identical,
    and two input orderings produce the same canonical output; quarantined rows are dropped."""

    def test_normalising_twice_is_byte_identical(self):
        self.assertEqual(normalize_findings.canonical_bytes(FIXTURE_DOC),
                         normalize_findings.canonical_bytes(FIXTURE_DOC))

    def test_input_order_does_not_change_output(self):
        shuffled = {**FIXTURE_DOC, "findings": list(reversed(FIXTURE_DOC["findings"]))}
        self.assertEqual(normalize_findings.canonical_bytes(FIXTURE_DOC),
                         normalize_findings.canonical_bytes(shuffled))

    def test_non_deterministic_rows_are_dropped(self):
        ids = [t["finding_id"] for t in normalize_findings.canonical_findings(FIXTURE_DOC)]
        self.assertNotIn("I4@a.cs#Auth.OnTokenValidated", ids)        # non_deterministic quarantined
        self.assertEqual(ids, ["A10@startup.cs#Startup.UseHangfireDashboard", "I3@m.cs#Mod.Expiration"])

    def test_differ_reports_convergence_and_manifest_delta(self):
        other = {**FIXTURE_DOC, "runMeta": {**FIXTURE_DOC["runMeta"], "generated": "2026-02-02T00:00:00Z"}}
        report = diff_runs.diff(FIXTURE_DOC, other)
        self.assertTrue(diff_runs.converged(report))                 # volatile runMeta is out of the diff
        self.assertTrue(report["same_commit"])
        self.assertEqual(report["onlyA"], [])


class DeterminismContractTests(unittest.TestCase):
    """Every check carries the shared-contract metadata and uses symbol anchors, not line numbers."""

    def test_scoring_inputs_are_valid_and_severity_derives(self):
        for cid, cls in REGISTRY.items():
            self.assertIn(cls.impact_class,
                          {"auth_bypass", "data_exposure_pii", "data_integrity", "dos", "info_leak", "maintainability"})
            self.assertIn(cls.scored_severity(), SEVERITY_BANDS, cid)
            self.assertTrue(cls.root_cause.startswith("RC-sec-"), f"{cid} root_cause")
            self.assertTrue(cls.canonical_id, f"{cid} missing canonical_id")
            self.assertTrue(cls.plan_id and cls.regression_test, f"{cid} missing plan/test")

    def test_anchors_are_symbols_not_line_numbers(self):
        # scan a small fixture per check and assert no anchor ends in :<line>
        self._assert_no_line_anchor("token-lifetime", "backend/src/Web.Core/M.cs", WEB_CORE)
        self._assert_no_line_anchor("token-blacklist", "backend/src/Web.Host/Startup/AuthConfigurer.cs", AUTH_WITH_EVENTS)
        self._assert_no_line_anchor("user-lockout", "backend/src/M.cs", "s.UserLockOutEnabled.WithDefaultValue(false);")

    def _assert_no_line_anchor(self, check_id, rel, text):
        import re as _re
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "backend").mkdir(parents=True, exist_ok=True)
        (root / "backend/Directory.Build.props").write_text(PROPS.format(v="0.43.37"))
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
        check = REGISTRY[check_id]()
        for i in check.scan(Repo(root)).issues:
            if i.anchor:
                self.assertIsNone(_re.search(r":\d+$", i.anchor), f"{check_id} anchor {i.anchor} is a line number")


class RegistryTests(unittest.TestCase):
    def test_every_check_is_documented(self):
        doc = (Path(__file__).resolve().parents[1] / "references" / "checks.md").read_text(encoding="utf-8")
        for cid, cls in REGISTRY.items():
            self.assertIn(f"`{cid}`", doc, f"{cid} has no section in references/checks.md")
            self.assertRegex(cls.doc, r"^references/checks\.md section \d+$")

    def test_every_check_is_in_the_skill_catalog(self):
        skill = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
        for cid in REGISTRY:
            self.assertIn(f"`{cid}`", skill, f"{cid} missing from the SKILL.md check catalog")


if __name__ == "__main__":
    unittest.main(verbosity=2)
