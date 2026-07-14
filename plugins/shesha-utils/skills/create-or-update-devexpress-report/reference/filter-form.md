# Filter Form — Shesha ConfigurableForm markup

The report's filter UI is a Shesha `ConfigurableForm` rendered by the viewer
(`parametersFilter/index.tsx`: `<ConfigurableForm mode="edit" formId={parametersFormPath} />`). On
**Apply**, the viewer takes each form field value and calls `setParameterValue(name, value)` on the
DevExpress report parameter of the **same name**. So every filter input's `propertyName` **must
equal** the report parameter `Name` and the `ReportingReportParameter.internalName`.

`scripts/build-report-xml.js --form <spec.json>` emits this markup, or assemble it inline using the
shapes below. The full set of supported components and their property shapes (from a survey of ~200
real Shesha forms) is in [form-components.md](form-components.md) — use `param.component` +
`param.componentProps` to emit any of them; the common cases are covered by data-type mapping here.

## Table of contents
- [Markup envelope](#markup-envelope)
- [Component per data type](#component-per-data-type)
- [Rules](#rules)

## Markup envelope

Form markup is a JSON object `{ components, formSettings }`. `parameterFormPath` on the report is
the JSON `FormIdentifier` `{"name","module"}` that resolves to this form.

```json
{
  "components": [
    { "...one input per filter..." }
  ],
  "formSettings": {
    "layout": "horizontal",
    "colon": true,
    "labelCol": { "span": 8 },
    "wrapperCol": { "span": 16 }
  }
}
```

Every component needs render-critical props or it won't display correctly (this was a real bug —
a minimal component silently fails to render). Include on **every** component: unique `id` (GUID),
`type`, `propertyName`, `componentName` (= propertyName), `label`, `labelAlign`, `parentId`
(`"root"`), `hidden`, `isDynamic:false`, `editMode:"editable"`, `validate:{}`,
`desktop:{}`,`tablet:{}`,`mobile:{}`, and the correct `version` per type. Shapes below are taken
from forms the Shesha designer actually produced.

## Component per data type

Map `ReportingReportParameter.type` (`GeneralDataType`) to a component (common props omitted for brevity):

**Text / Guid (1, 0)** — `type:"textField"`, `version:4`.

**Numeric (6)** — `type:"numberField"`, `version:4`.

**Date (2) / DateTime (4)** — `version:5`:
```json
{ "id":"<guid>", "type":"dateField", "propertyName":"dateFrom", "componentName":"dateFrom",
  "label":"From Date", "labelAlign":"right", "parentId":"root", "hidden":false, "isDynamic":false,
  "editMode":"editable", "validate":{"required":false}, "desktop":{},"tablet":{},"mobile":{},
  "version":5, "showTime":false, "dateFormat":"DD/MM/YYYY", "timeFormat":"HH:mm:ss",
  "defaultToMidnight":true, "showNow":false, "disabledDateMode":"none", "range":false }
```
DateTime → `showTime:true`, `dateFormat:"DD/MM/YYYY HH:mm:ss"`. For a period picker set
`range:true` (value is a two-element array; split it to two params in `onChangeCustom`).

**Time (3)** — `type:"timeField"`, `version:4`.

**Boolean (5)** — `type:"checkbox"`, `version:4`.

**ReferenceList (8) / MultiValueReferenceList (9)** — `version:7`. `referenceListId.name`/`module`
are **not** hardcoded — resolve them from the target site (see
[Resolve names from the API](#resolve-names-from-the-api-never-hardcode)):
```json
{ "id":"<guid>", "type":"dropdown", "propertyName":"<paramName>List", "componentName":"<paramName>List",
  "label":"<label>", "labelAlign":"right", "parentId":"root", "hidden":false, "isDynamic":false,
  "editMode":"editable", "validate":{}, "desktop":{},"tablet":{},"mobile":{}, "version":7,
  "dataSourceType":"referenceList", "useRawValues":false,
  "referenceListId":{ "name":"<resolved full reflist name>", "module":"<resolved module>" },
  "mode":"multiple", "valueFormat":"simple",
  "onChangeCustom":"form.setFieldValue('<paramName>', value?.join(','))" }
```
`referenceListId.name` is the **full** reflist name (`<module>.<shortName>`); `module` is the
namespace. Single (8) → `mode:"single"` and no `onChangeCustom`.

**EntityReference (10)** — `type:"autocomplete"`, `version:6` (NOT `entityReference`).
`entityTypeShortAlias`/`entityDisplayProperty` are resolved from the site, not hardcoded:
```json
{ "id":"<guid>", "type":"autocomplete", "propertyName":"<paramName>List", "componentName":"<paramName>List",
  "label":"<label>", "labelAlign":"right", "parentId":"root", "hidden":false, "isDynamic":false,
  "editMode":"editable", "validate":{}, "desktop":{},"tablet":{},"mobile":{}, "version":6,
  "dataSourceType":"entitiesList", "useRawValues":true,
  "entityTypeShortAlias":"<resolved entity type>",
  "entityDisplayProperty":"<resolved display property>", "mode":"multiple",
  "onChangeCustom":"form.setFieldValue('<paramName>', value?.join(','))" }
```

## Resolve names from the API (never hardcode)

Reference-list names, modules, entity types, and display properties are **project-specific** —
always look them up on the **target site** before building the spec (the build script only ever
uses the values you pass in `param.referenceListName`/`referenceListNamespace`/`entityTypeShortAlias`/
`entityDisplayProperty`). The endpoints mirror the generate-sql-query skill; full details in
[data-model.md](data-model.md#discovering-valid-values). In short:

- **Reference list** (for a reflist filter): find it by short name via
  `Entities/GetAll?entityType=Shesha.Framework.ReferenceList&quickSearch=<name>` → read the returned
  **full `name`** and its **`module`**; confirm items via the `ReferenceListItem` query. Never assume
  the namespace prefix.
- **Entity** (for an entity filter): find the class via
  `EntityConfig/GetMainDataList` (match on `className`) → use its type name/alias and pick a display
  property from `ModelConfigurations/{id}`.

If a name can't be resolved on the target site, stop and ask — do not guess.

## Multi-value bridging (important)

A multi-select yields an **array**, but the SQL `string_split(@param,',')` predicate needs a
**comma string**. So for multi-value filters the visible control's `propertyName` is `"<name>List"`
and its `onChangeCustom` writes the real SQL param: `form.setFieldValue('<name>', value?.join(','))`.
The report parameter / `internalName` / SQL token stays `<name>`; `setFieldValue` puts it in the
submit store even without its own visible component. Single-value filters need no bridge — the
control's `propertyName` is the param name directly.

## formSettings

```json
{ "layout":"horizontal", "colon":true, "labelCol":{"span":6}, "wrapperCol":{"span":18},
  "version":6, "modelType":"", "dataLoaderType":"gql", "dataSubmitterType":"gql" }
```

## Rules

- Single-value: `propertyName === internalName === report parameter Name === SQL @param`.
  Multi-value: visible control is `"<name>List"`, bridged to `<name>` via `onChangeCustom`.
- Order fields by the parameter `parameterOrderIndex`; the viewer otherwise sorts alphabetically.
- Keep the form flat (all inputs at `parentId:"root"`) unless grouping is wanted — then wrap in a
  `container` and set each input's `parentId` to the container `id`.
- Do not add Apply/Cancel buttons — the viewer supplies them around the form.
- Hidden/fixed parameters (`hideParameter:true`) still emit a component with `hidden:true` (or set
  a `ReportingReportParameter.parameterValue` default).
