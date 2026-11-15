---
name: harden-permissions
description: Uses Playwright to set permissions on unsecured Shesha API endpoints via the permissioned-objects admin UI. Restricts write operations to app:Configurator. Use when the user wants to harden, secure, or lock down API endpoints, fix permissioned-objects, restrict access to admin-only services, or add authorization to unprotected app services in a Shesha application.
---

# Harden Permissions

Automates permission changes on the Shesha permissioned-objects page (`/dynamic/Shesha/permissioned-objects`) using Playwright.

## Prerequisites

Playwright must be installed globally (`npm i -g @playwright/test`). Verify with `npx playwright --version`.

## Procedure

1. Ask the user for:
   - **Base URL** (e.g. `http://localhost:3000`)
   - **Admin credentials** (username and password)

2. Run the script in dry-run mode first to preview changes:
   ```bash
   node <skill-dir>/scripts/harden-permissions.js <baseUrl> <username> '<password>' --dry-run
   ```

3. After user confirms, run without `--dry-run`:
   ```bash
   node <skill-dir>/scripts/harden-permissions.js <baseUrl> <username> '<password>'
   ```

4. **Restart the backend and re-check.** Re-open the permissioned-objects page (or
   `PermissionedObject/GetAll`) after a restart and confirm every change is still there. Some
   framework records are hard-coded and re-applied at start-up, so a change can look applied
   and be gone after the next start (see "Framework version caveats").

5. Report the results. If any endpoints fail, or a change did not survive the restart, note
   them for manual follow-up.

## What the script changes

### Class-level `Requires permissions` + `app:Configurator`
All endpoints in these services become admin-only:
- ProcessMonitor
- DeviceForceUpdate
- DeviceRegistration
- SmsGateways

### Class-level `Any authenticated` + method-level `app:Configurator` on write ops
Read endpoints stay open to logged-in users. Write operations require `app:Configurator`:

| Service | Restricted methods |
|---|---|
| Area | Create, Delete, Update, MoveArea |
| ConfigurableComponent | Create, Delete, Update, UpdateSettings |
| EntityConfig | Create, Delete, Update, RemoveConfigurationsOfMissingClasses |
| EntityProperty | Create, Delete, Update |
| ReferenceList | Create, Delete, Update, ClearCacheFull |
| ShaRole | Create, Delete, Update |
| Notification | Publish |
| NotificationMessage | Create, Delete, Update |
| QuestionAnswers | Delete |

### Specific methods only (no class-level change)
| Service | Methods | Access |
|---|---|---|
| Session | ClearPermissionsCache | app:Configurator |
| UserManagement | Create, CompleteRegistration | app:Configurator |

## Customization

Edit the `CHANGES` array in `scripts/harden-permissions.js` to add/remove services or endpoints.

## Framework version caveats

Check these before running on Shesha 0.43.41 or later; they came from a post-upgrade re-audit:

- **Permission names were renamed.** `app:Configurator` became `Application-Configure`,
  `pages:maintenance` became `Application-Maintenance` and `Pages.Users` became `User-Manage`.
  Use the names the running version lists on the permissions page; a requirement naming a
  permission that no longer exists denies everyone. Update the `CHANGES` array to match.
- **Some records cannot be configured.** 0.43.41 marks the user-management service not
  configurable, hard-codes `UserManagement/Create` to `User-Manage`, and re-applies it at
  start-up. The `UserManagement` row above will not survive a restart there. Control who can
  create users through who holds `User-Manage` instead.
- **Built-in rules can widen on upgrade.** The same release made `User/ResetPassword` accept
  `User-ResetPassword` **or** `User-Manage`. Review which roles hold each. Compare before and
  after an upgrade with `auditing-application-security`'s `drift.py`.

## What this skill does not cover

- **Entities.** This script changes service endpoints only. Framework, ABP and Enterprise
  entities (user accounts, bank accounts, user roles and tokens, settings, audit logs) are
  reached through generic dynamic CRUD and need entity-action records. Use
  `shesha-access-control` (check SEC-FW), shipped as a migration.
- **Who may change an administrator's credentials.** Use `shesha-access-control` (check
  SEC-ESC).

## What is NOT changed
- Services already marked `(permissioned)` in the UI
- `[AbpAllowAnonymous]` endpoints (password reset, login)
- Read-only endpoints needed by forms runtime (Metadata, ReferenceList.GetItems, etc.)
- The `Aaaaaaa` test service (flag for removal instead)
