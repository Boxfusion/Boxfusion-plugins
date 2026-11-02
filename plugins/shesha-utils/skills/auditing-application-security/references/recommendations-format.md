# Writing `{package}-recommendations.md`

The catalogue is for machines and for the next audit. This file is for the developer who has
to fix things this sprint. One file per package, written from `digest.py` output plus the
catalogue rows it points at.

## Contents
- Who reads it, and the rules that follow from that
- Language rules
- The structure
- Section order and what belongs in each
- Worked example of one section
- The summary
- Annexures
- The index file
- Before you finish

## Who reads it, and the rules that follow from that

A developer on the team that owns this package. Possibly junior. They have not read the
catalogue, do not know the audit's vocabulary, and will act on the first three items and skip
the rest if the document is long.

So:

1. **Only negative findings that you recommend actioning.** No "we checked X and it was
   fine". No low-priority padding. A section with nothing to fix is omitted, not written as
   "no issues found".
2. **Priority order inside every section**, most urgent first.
3. **Succinct.** One or two lines per finding. If a package has forty rows of the same shape,
   report the pattern and the count and name the worst five — never a forty-row table.
4. **Every finding says where, what, and what to do.** A finding without a fix is a
   complaint.
5. **Where the fix is code, point at the annexure**, do not inline a tutorial.

## Language rules

No security jargon. Not because the reader is not clever, but because jargon is where a
recommendation stops being actionable.

| Do not write | Write |
|---|---|
| Unauthenticated endpoint | Anyone can call this without logging in |
| IDOR / BOLA | A logged-in user can read another person's record by changing the id in the URL |
| Broken function level authorization | Any logged-in user can run this, including someone with no role at all |
| Missing row-level security | Users see everybody's rows, not just their own |
| Anonymous attack surface | Parts of the API that work with no login |
| Privilege escalation vector | A user could give themselves more access than they should have |
| CORS misconfiguration | Any website can make requests to this API using a logged-in user's session |
| Hardcoded credential | A password/key is committed in the repository, so everyone with the code has it |
| Deny-all permission set | The rule blocks everyone, including administrators — it is almost certainly a mistake |

Also:

- Say what an attacker or a curious user could actually *do*, in terms of this application's
  data: "read any employee's ID number and date of birth", not "sensitive data exposure".
- Never present a guess as a fact. "The name suggests this holds banking details — confirm"
  is fine. "This exposes banking details" is not, unless you looked.
- Where a claim is derived rather than observed, say so in the same sentence.

## The structure

```markdown
# Security Recommendations — {Package}

What this package is: {one line - app-owned module | imported package | front-end code}
How things here get fixed: {edit this repository | configure the database or upgrade the package}
Audit run: {YYMMDD-HHMM} | Backend: {url} | Default access for unconfigured endpoints: {name}

{One short paragraph: the shape of what was found. Two or three sentences, no lists.}

## 1. {Section title, in plain words}

{Two or three sentences: what kind of problem this section is about, and why it matters
here. Written so someone who has never seen the audit understands the risk.}

- **{Where}** — {what is wrong, and what someone could do with it}.
  Fix: {the concrete change}. {Annexure ref, e.g. "See Annexure A2."}
- **{Where}** — ...

{Where a pattern repeats: "The same applies to 23 other endpoints on this service - the
full list is in `catalog/{package}-endpoints.json`, filtered on
`recommendedAction: RESTRICT`."}

## 2. ...

## Act on these first

1. {…}

## What this did not cover

{Checks skipped, data that was missing, and what that means. Not optional.}
```

## Section order and what belongs in each

Use `digest.py`'s themes; they are already in priority order. Drop any section with no rows.

| # | Section title to use | Covers |
|---|---------------------|--------|
| 1 | Things anyone can reach without logging in | `effectiveAccess = AllowAnonymous`, anonymous probe hits, forms open without a login |
| 2 | Rules that block everyone, including administrators | `RequiresPermissions` with no permission named; permissions no role holds |
| 3 | How the application is hosted | CORS, the error log, Swagger, the GraphQL console, missing response headers, the Hangfire dashboard |
| 4 | Passwords and keys stored in the code | Committed signing keys, connection-string passwords, API keys |
| 5 | Things every logged-in user can reach | `AnyAuthenticated` on administrative or sensitive operations |
| 6 | Users can see other people's records | Missing global specifications; observed IDOR and unscoped list results |
| 7 | Login sessions and repeated attempts | Token lifetime, sign-out behaviour, lockout, rate limiting |
| 8 | Parts of the API nothing uses | Unreferenced entities, actions and endpoints, with the safety-gate caveat |
| 9 | Screens, forms and code nothing opens | Orphaned form configurations and dead coded screens |
| 10 | Permissions and roles that do nothing | Orphaned permissions, roles with no permissions |
| 11 | Out-of-date libraries | Dependency advisories, runtime separated from build-only |
| 12 | Needs a decision before anything changes | Everything marked `REVIEW`: opaque references, plausible external callers, unattributed endpoints |

For an **imported package**, keep the same sections but state in the header that nothing here
is fixed by editing this repository, and give each finding a configuration or upgrade route.
Where a row is `hardcoded`, say plainly that a configuration change will be undone on the
next restart and what the remaining options are.

## Worked example of one section

```markdown
## 1. Things anyone can reach without logging in

Some endpoints answer requests that carry no login at all. Anything they return is public,
and anything they change can be changed by anyone who knows the URL.

- **`GET /api/services/Hcm/HcmHealthCheck/Check`** — answers without a login. It returns
  only a status, so the risk is low, but it is set in code (`AllowAnonymous`), which means
  changing it in the admin UI will be undone on the next restart.
  Fix: if it is there for a load balancer, keep it and note why. Otherwise remove the
  attribute from the service. See Annexure A1.

- **The Elmah error log at `/elmah`** — answers without a login and returns stored errors
  including the request headers, which contain users' login tokens. Anyone who finds the URL
  can take a token and use it as that user. One captured token in this run was still valid.
  Fix: wrap `app.UseSheshaElmah()` in a development-only check **and** rotate the signing
  key, because the tokens already stored stay usable until you do. See Annexure E2.
```

Note what makes it usable: the exact path, what someone could do, whether the claim was
observed or derived, and a fix with a pointer.

## The summary

Every file ends with **Act on these first** — at most five numbered items, from that package,
in the order they should be done. Each is one line naming the thing and the action.

The index file (`recommendations-index.md`, see below) carries the top five **across all
packages**. That is the list a lead reads. Include an item there only if it is genuinely
urgent; four real items beat five padded ones.

Ordering rule when priorities tie: the app-owned finding first, because it can be fixed
today.

## Annexures

Do not restate `remediation-guide.md`. Each recommendation cites the section (`Annexure A2`,
`Annexure C`), and every recommendations file ends with:

```markdown
## Annexures

Step-by-step remediation, with code: `references/remediation-guide.md` in the `auditing-application-security` skill (`shesha-utils` plugin, Boxfusion/Boxfusion-plugins)

| Annexure | Covers |
|---|---|
| A | Requiring a login or a permission on an endpoint |
| B | Requiring a permission on entity data |
| C | Restricting which rows a user can see |
| D | Turning off an endpoint or an entity API |
| E | Fixing the web host — CORS, error pages, Swagger, headers |
| F | Secrets: moving them out and rotating them |
| G | Login sessions, tokens and repeated attempts |
| H | Permissions and roles that do nothing |
| I | Forms and screens nothing opens |
| J | Verifying a change actually took effect |
```

Where a fix needs something the guide does not cover, write it into the guide rather than
into the report — the next run then inherits it.

## The index file

One `recommendations-index.md` at the root of the run directory:

```markdown
# Security Recommendations — {Application}

Run {YYMMDD-HHMM} | Backend {url} | Branch {branch}
Package versions: Shesha {v} | Enterprise {v} | SaGov {v} | reactjs {v}

## The five things to do first
1. **{package}** — {one line} → `{package}-recommendations.md`, section {n}

## Per package
| Package | Owned by | Urgent | Total recommendations | File |

## How much of the application this covers
Front-ends scanned {n of m} | Opaque references {n} in {n} forms
Second (low-privilege) account used: {yes | no - object-level checks not tested}
Live probes: {run | skipped, because ...}
Missing inputs: {list, or none}

## Compared with the previous run
{Fixed since, still open, newly found - or "baseline audit".}
```

## Imported packages whose source was not scanned

If `_index.json` → `confidence.packageSourcesNotScanned` is non-empty, the index must say so
in its coverage section, in plain words:

> The source of `@shesha-io/enterprise` and `Shesha.Workflow` was not available, so the calls
> their own screens make could not be seen. Endpoints and forms only those screens use look
> unused here. They are marked "review" rather than "disable" (N rows); do not remove any of
> them without checking the package first. Supplying the source lifts this.

Name each package (verify_run checks each `<package> source` missing input appears), give the
capped count, and never present those rows as unused in a package report.

## Before you finish

- [ ] Every recommendation names a package, a place, an impact and a fix.
- [ ] No section says "no issues found".
- [ ] No jargon from the table above survives.
- [ ] Every repeated pattern is summarised with a count and a pointer, not enumerated.
- [ ] Every derived claim is labelled derived.
- [ ] Every count matches the catalogue and `digest.py`.
- [ ] Skipped checks and missing inputs are stated, per package and in the index.
- [ ] Top five are genuinely the top five, app-owned first on ties.
