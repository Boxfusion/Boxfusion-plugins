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

4. Report the results. If any endpoints fail, note them for manual follow-up.

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

## What is NOT changed
- Services already marked `(permissioned)` in the UI
- `[AbpAllowAnonymous]` endpoints (password reset, login)
- Read-only endpoints needed by forms runtime (Metadata, ReferenceList.GetItems, etc.)
- The `Aaaaaaa` test service (flag for removal instead)
