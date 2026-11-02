# Step 7 — Probing beyond the framework matrix

Read at Step 7 of `SKILL.md`, after the first `probe.py` run.

`probe_matrix.json` ships the **framework** surface. This application's own surface is
different on every deployment, so extend the matrix from the catalogue and probe again:

```bash
python $R/extend_probe_matrix.py --run-dir $RUN --dry-run    # see what it would add
python $R/extend_probe_matrix.py --run-dir $RUN              # add it
python $R/probe.py --repo-root . --lowpriv-user <u> --lowpriv-password <p>
python $R/build_catalogs.py --repo-root . --run-dir $RUN     # so the verdicts land
```

It generates an anonymous probe for every endpoint resolving to AllowAnonymous, a
low-privilege probe for the sensitive endpoints open to any authenticated user (capped per
package — a handful converts the derived claim into an observed one, hundreds just bloat the
matrix), and a read of every sensitive entity with a live read route. Expectations come from
the **reviewed** disposition, so a `KEEP`/`KEEP-INFRA` endpoint is generated as
`anonymous-ok` rather than manufacturing a false finding on the login and password-reset
family every run.

**Write endpoints are generated `enabled: false`.** "Probe every unprotected write endpoint"
and "corrupt the database" are the same request, so those are documented but not sent;
`probe.py --include-disabled` fires them, and only against a database you can restore.

This step was skipped on the first run of this skill, and it cost real coverage: the three
`ConfigurationItemUtilities` routes — any logged-in user rewriting every form in a module —
were never probed and were found by reading an unattributed bucket by hand.

For anything returning 200, capture the body and quote the field names. "Returns 200 with
employee identity numbers and salary bands" gets fixed; "returns 200" does not.

`object_auth.py` answers the question endpoint probes structurally cannot: may this user see
**this row**. Its remediation is a global specification, **not** an entity action permission —
a permission gates the endpoint, a specification gates the row. Saying "configure entity
permissions" in response to an IDOR finding is wrong advice, and it is the mistake an
endpoint-focused audit is most likely to make.

`posture_scan.py` covers token and session policy, rate limiting and lockout, dependency
advisories and secrets in tracked configuration. Judge a signing key by **entropy, not
length**: 32 alphanumeric characters is ~165 bits and is not brute-forceable, so do not report
it as weak — a committed key of adequate strength is a *disclosure* finding whose fix is
rotation. Read rate-limiting **configuration**; never run a brute-force burst to prove its
absence.
