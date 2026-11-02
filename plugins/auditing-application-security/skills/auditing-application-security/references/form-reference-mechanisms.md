# How Shesha Forms Reference Endpoints

## Contents
- Why this matters for disable decisions
- 1. Entity binding (modelType, entityType)
- 2. Owner binding (ownerType)
- 3. URL properties on components
- 4. Source-type discriminators
- 5. Reference lists
- 6. Form references and transitive resolution
- 7. Action configurations
- 8. Embedded JavaScript
- 9. Data-source components
- What cannot be resolved statically

## Why this matters for disable decisions

A form configuration is JSON in the database. An endpoint reference inside it may be an explicit URL
string, or it may be implied by an entity binding, an owner type, a reference list id, or a form id
that pulls in another form's entire reference set. Miss one mechanism and an endpoint that the UI
genuinely calls looks unreferenced — and disabling it breaks the application.

Every mechanism below is a way an endpoint can be reached without its URL appearing anywhere. Treat
this file as the checklist that makes "unreferenced" trustworthy.

## 1. Entity binding (modelType, entityType)

A form's root `modelType`, or a component's own `entityType`, binds to an entity. The framework
resolves that entity's CRUD endpoints from metadata at
`/api/services/app/Metadata/Get?container={entityType}` (which returns `apiEndpoints` with create,
read, update and delete entries) and calls `/api/dynamic/{module}/{Entity}/Crud/{Action}`.

A form-level `modelType` implies `Get`, `Create`, `Update` and `Delete`. Record the metadata call
itself as referenced too.

Components carrying their own `entityType`, independent of the form's `modelType`:
`datatableContext`, `dataSource`, `dataList`, `entityPicker`, `entityReference`, `autocomplete`,
`charts`, `kanban`, `configurableItemAutocomplete`, `formAutocomplete`, `notificationAutocomplete`,
`referenceListAutocomplete`, `subForm`, and the legacy `listControl`.

Collect `entityType` from **every** component in the markup, not only from that list — new
components appear over time.

## 2. Owner binding (ownerType)

`fileUpload`, `attachmentsEditor`, `image` and `notes` scope themselves to an owning entity through
`ownerType` plus an owner id. This drives the file and note endpoints:
`/api/StoredFile/FilesList`, `/Upload`, `/UploadNewVersion`, `/Download`, `/Delete`, and the Notes
app service.

`ownerType` is an entity reference that carries no `entityType` key, so a scan looking only for
`entityType` and `modelType` misses it completely. Record `ownerType` both as an entity reference
and as a reference to those StoredFile and Notes endpoints.

## 3. URL properties on components

Search these keys anywhere in the markup tree:

| Key | Where it appears |
|-----|-----------------|
| `url` | `API Call` action arguments; `charts` in url mode. The most common, and easy to overlook |
| `endpoint` | `datatableContext`, `dataSource`, `charts` when the source type is Url |
| `customReorderEndpoint` | `datatableContext` row reordering |
| `dataSourceUrl` | `autocomplete`, `entityPicker`, `entityReference`, `subForm`, `kanban`, `charts`, file components |
| `getUrl`, `postUrl`, `putUrl`, `deleteUrl` | `subForm` and CRUD-capable components |
| `customCreateUrl`, `customUpdateUrl`, `customDeleteUrl` | components overriding individual verbs |
| `getEntityUrl`, `quickviewGetEntityUrl` | `entityReference`, quickview, `autocomplete` |
| `autocompleteUrl` | `autocompleteTagGroup`, column filters |
| `getListUrl` | url-backed table repository |
| `submitUrl`, `fetchUrl`, `getFormUrl` | form-level submit and fetch overrides |
| `customUrl`, `customApiUrl` | generic overrides; `customApiUrl` is the legacy `listControl` |
| `targetUrl`, `navigateToUrl`, `onSuccessRedirectUrl` | navigation targets — usually app routes, not API endpoints. Collect separately and only report those matching `/api/` |

Do not add `apiUrl`, `sourceUrl` or `actionUrl` — these appear nowhere in the Shesha React codebase
and will never match.

## 4. Source-type discriminators

Several components hold both an entity binding and a URL, with a mode flag deciding which is live.
The inactive property usually still holds a stale value from an earlier configuration. Recording
both produces false positives — endpoints reported as referenced that are never called.

| Component | Discriminator | Values and the live property |
|-----------|--------------|------------------------------|
| `datatableContext`, `dataSource` | `sourceType` | `Entity` uses `entityType`; `Url` uses `endpoint`; `Form` uses `propertyName` and calls nothing |
| `autocomplete`, `entityPicker` | `dataSourceType` | `entitiesList` uses `entityType`; `url` uses `dataSourceUrl` |
| `dropdown`, `radio`, `checkboxGroup` | `dataSourceType` | `referenceList` uses `referenceListId`; `values` is static and calls nothing |
| `charts` | `dataMode` | `entityType` uses `entityType`; `url` uses `url` |

Record the mode alongside each reference and mark references from the inactive branch as
`stale-config` rather than counting them as live. Reading a binding without its discriminator is the
main source of false positives in this catalog.

## 5. Reference lists

`referenceListId` (an object with `module` and `name`) and the legacy `referenceListName` appear on
`dropdown`, `radio`, `checkboxGroup`, `refListStatus`, `referenceListAutocomplete` and any reflist
table column. Each resolves at runtime to `/api/services/app/ReferenceList/GetByName`.

These are neither entities nor explicit URLs, so they need their own category.

## 6. Form references and transitive resolution

`formId` and `formIdentifier` — a `{module, name}` object or a GUID — appear on `subForm`,
`dynamicView`, `entityReference`, `childEntitiesTagGroup`, and inside `Show Dialog` and
`Show Confirmation Dialog` action configurations.

Each implies a `FormConfiguration` fetch **and inherits every endpoint the referenced form itself
references.** Build the form-to-form graph and resolve it transitively with cycle protection —
forms can embed each other. Without this, an endpoint reached only through a subform or a dialog is
wrongly reported as unreferenced, which is exactly the kind of mistake that breaks an application
when acted on.

`subForm` also has `formSelectionMode`:
- `name` — static `formIdentifier`, resolvable
- `dynamic` — resolved at runtime from `entityType` plus `formType`; record the pair and treat every
  form of that `formType` as potentially reachable
- `expression` — chosen by a JavaScript expression, **not statically resolvable**; flag it

## 7. Action configurations

Buttons, toolbar items, row actions and lifecycle hooks use `actionConfiguration` objects, and they
nest — inside `onClick`, `onSuccess`, `onError`, `onBeforeRowReorder`, `onAfterRowReorder`, and
inside dialog configurations. Each has `actionOwner` and `actionName`.

| `actionName` | Where the reference lives |
|-------------|--------------------------|
| `API Call` | `actionArguments.url`, plus `verb`, `parameters`, `headers` |
| `Execute Script` | `actionArguments.expression` — arbitrary JS, parse per section 8 |
| `Show Dialog`, `Show Confirmation Dialog` | `actionArguments.formId` — transitive form reference |
| `Navigate` | an app route unless it matches `/api/` |
| `Export to Excel`, `Export items`, `Import items`, `Download as JSON` | the owning table or entity's export and import endpoints |
| `Sign In` | the TokenAuth endpoints |

Argument values may themselves be JavaScript expressions rather than literals. If a value does not
look like a literal URL, treat it as a script.

## 8. Embedded JavaScript

Lifecycle hooks and expression properties hold JavaScript that runs in the browser. Search these
keys for string values:

`expression`, `executeExpression`, `onExecute`, `customJsCode`, `actionScript`, `jsCode`, `code`,
`onChangeCustom`, `onBlurCustom`, `onFocusCustom`, `customVisibility`, `customEnabled`,
`onBeforeDataLoad`, `onAfterDataLoad`, `onPrepareSubmitData`, `onBeforeSubmit`, `onSubmitSuccess`,
`onSubmitFailed`, `onValuesUpdate`, `onRowSave`, `onRowSaveSuccess`, `customFilter`, `filter`,
`permanentFilter`, `content`, `defaultValue`, and any key suffixed `Expression` or `Custom`.

The form JavaScript context exposes `data`, `form`, `contexts`, `pageContext`, `globalState`,
`setGlobalState`, `selectedRow`, `moment`, `message`, `fileSaver`, `query`, `initialValues`,
`parentFormValues` and `http`. Only `http` reaches the backend directly, so it is the primary
signal. It is an axios wrapper with `get`, `post`, `put`, `patch`, `delete`, `head` and `options` —
the last two are easy to omit from a pattern list.

Match `/api/` string literals, `http.` calls across all seven verbs, `fetch(`, axios calls, and
URL-holding constants. Extract endpoints with a pattern such as `/api/[^\s"'`}\)]+`.

## 9. Data-source components

`datatableContext` binds an entity type and queries its `GetAll`. `entityPicker` and `autocomplete`
use the entity's autocomplete or list endpoint. `dataList` and `kanban` sit on top of a table
context. All are governed by the discriminators in section 4.

## What cannot be resolved statically

Report these in a dedicated unresolvable list rather than dropping them. Each is a potential
uncatalogued endpoint, and — critically — anything appearing here must never be treated as evidence
that an endpoint is unused:

| Reason | Example |
|--------|---------|
| `concatenated-url` | a URL built by string concatenation |
| `template-literal-url` | a URL built in a template literal from a variable |
| `dynamic-verb` | `http[verb](url)` |
| `endpoint-from-data` | the endpoint read from `data`, `globalState`, a context or a setting |
| `endpoint-from-setting` | the endpoint stored in application settings |
| `expression-selected-form` | `subForm` with `formSelectionMode: expression` |

Record for each: the form name, the component id, the markup key, and a snippet preview.
