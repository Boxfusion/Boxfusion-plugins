# Data safety and access

## Which database

1. **Default: a local copy of the QA database,** provided by the user. All inspection and most reproduction happens here. If you don't have one, ask the team lead or DevOps for the latest QA `.bacpac` or `.bak`, and restore it locally as `<System>_QA_TLC`.
2. **Production copy: only by escalation, and only when the QA evidence justifies it.** Don't ask up front. Raise it only when a finding proven on the QA copy is serious, and likely present in production, and production data is needed to prove its scale. Examples: lost calls, data exposure, or a large failure rate. Say so plainly and give the evidence. Then ask the user to **escalate to the IT Manager**, who either:
   - grants permission to obtain a production backup (and says where it may be stored and when it must be deleted), or
   - hands the work to more senior staff.

   Never suggest a graduate obtains production data without that permission. **A graduate's laptop never holds a production copy, even with permission:** the IT Manager names a senior person or machine. Record the decision in `diagnosis/01-recon.md`.
3. **Never connect to a live production database or server** for diagnosis. Read access to production telemetry (App Insights) is fine through the user's own sign-in, with aggregate queries only. For production Query Store or DMVs, ask the IT Manager the same way, and use read-only, aggregate queries.

## Before any backend starts (every copy, QA or production)

**Never start a backend against the developer's own database or a shared one.** Every copy is isolated and proven first.

**Isolate integrations automatically, defaults included, without asking.** Save the original values to `dbo.zz_LocalIsolationBackup`.
1. **Inventory before any backend starts.** List every outbound integration: mail, SMS, push, webhooks, message buses (RabbitMQ/MassTransit), (S)FTP, external APIs, scheduled jobs. Cover **both** the saved setting values **and the code or package defaults** used when no value is saved. Read the settings classes, and search the referenced packages for default hosts. Example: Shesha.MassTransit 5.1.7 defaults to a shared BoxFusion test broker.
2. **Cut off what the app can start without:**
   - SMS: switch it off, and point the gateway hosts at `isolated.invalid`;
   - SMTP: point the hosts at `isolated.invalid`;
   - push: clear the notifier;
   - webhooks: deactivate them;
   - Hangfire: empty the `schedule` set, so the source environment's scheduled jobs don't fire on first start;
   - any other outbound integration (telephony, payment, FTP, third-party APIs): a dead host.
3. **Stand in locally for what the app needs to start.** Example: a backend that won't boot without its message bus. Start a local container (e.g. `docker run -d --name tlc-rabbit -p 5672:5672 rabbitmq:3-management`) and point the copy at it. **Never point at a shared or real server.**
4. **Write settings with the exact property names** of the setting's class. Read the settings interface; don't guess the JSON keys.
5. **Ask the user only if isolating an integration would need an application code change.** Record that hard dependency as a finding.
6. Take a `COPY_ONLY` backup of the isolated state. Every probe run restores to it afterwards.
7. **Report what was done** in `00-test-readiness.md`: what was cut off, what was stood in, and the canary result.

Re-verify isolation before **every** backend start.

**Point the backend at the copy by config file, and prove it before anything else.**
- **Use a git-excluded `appsettings.{Environment}.json`.** Don't rely on environment variables: Shesha hosts may build their configuration from the appsettings files only, so `ConnectionStrings__Default` set as an environment variable can be silently ignored and the backend starts on another database.
- **Verify the connection immediately after start-up (the canary),** before any test, login or long wait:
  1. Make one harmless request that leaves a trace, e.g. a failed login with a `zzprobe-canary` username.
  2. Confirm the trace landed in the copy (login-attempts table: `Frwk_UserLoginAttempts` on 0.43–0.44, `frwk.user_login_attempts` on 0.45+ — resolve the name for the version, see `framework-standards.md`) and not in any other database.
  3. If it landed anywhere else, **stop the backend at once**, inventory what it wrote there (rows created or modified since start, jobs run, notifications queued), and tell the user.
- **Where the host allows it, start with background job processing disabled** until the check passes. Jobs fire on start-up and would otherwise run against whatever database the host really connected to.

## Preparing a production copy (when approved)

A `.bacpac` exported from a live database is not a consistent snapshot. Expect and repair these, then isolate it as above:
- **Constraints left off.** Foreign keys stay disabled and untrusted when the import stops at the first conflict.
  - Find the orphan rows.
  - Rows created during the export window (compare their timestamps with the file time) are export artefacts: unlink or delete them on the copy.
  - Re-enable every constraint `WITH CHECK CHECK`.
  - Report anything that isn't explained by the export window. It may be real bad data.
- **Triggers left off.** Compare with QA, and re-enable framework bookkeeping triggers.

## Personal data

- Never print, export or paste real names, phone numbers, ID numbers, addresses or health data. Report counts, booleans, status codes and ids of synthetic records only.
- Never use real people's records as probe inputs (e.g. looking up a real caller's number). Create synthetic records instead.
- App Insights: aggregate queries only, with digits masked (`replace_regex(x, @"\d", "#")`) on any message text.
- Production copies stay on the approved machine and are deleted when the diagnosis ends, as the IT Manager specified.

## Logins

- Use only the test logins in the project's test plans, seed files or `.env`. Passwords live only in the gitignored `.env`.
- On a production copy, create synthetic users (`zzprobe-…`) and give them the password hash of a known test user from QA. Never obtain, reset or crack a real user's password, and never use a real person's account.
- Keep tokens in memory. Never write them to files or output.

## Secret values

- Probes that touch secrets (settings endpoints, committed credentials, package defaults) record **presence only**: status code, empty or not, length band, or "hash matches / doesn't match". Never print, log, store or paste a secret value, including into findings, hand-backs or this run's learnings.

## Probe hygiene

- Mark every synthetic record `ZZ-PROBE` and keep a manifest.
- Back up before, restore after, and verify the copy is clean.
- When proving production behaviour, run the code that matches production: find it by the newest migration, and check out that commit in a worktree. Running newer code would migrate the copy.
