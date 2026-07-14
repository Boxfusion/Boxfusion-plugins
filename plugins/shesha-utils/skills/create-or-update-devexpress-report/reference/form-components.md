# Form Component Catalog

The component shapes below are reverse-engineered from ~200 real forms in a live Shesha system
(64 distinct component types were found). `scripts/build-report-xml.js` (`COMPONENT_DEFAULTS`)
emits these; this file is the reference for which components exist and their render-critical props.

A filter parameter maps to a component two ways:
- **By data type** — the parameter's `dataType` (`GeneralDataType`) picks a default component
  (`DATATYPE_COMPONENT` in the script).
- **Explicit** — set `param.component` to any type below and (optionally) `param.componentProps`
  to override/extend the defaults. This is how the skill supports *any* component.

Every generated component also gets the common base props: `id` (GUID), `type`, `propertyName`,
`componentName`, `label`, `labelAlign`, `parentId:"root"`, `hidden`, `isDynamic:false`,
`editMode:"editable"`, `validate:{}`, `desktop/tablet/mobile:{}`.

## Table of contents
- [Data-type → default component](#data-type--default-component)
- [Input components](#input-components)
- [Reference-list / entity components](#reference-list--entity-components)
- [Specialised inputs](#specialised-inputs)
- [Layout / display components](#layout--display-components)
- [Overriding & multi-value](#overriding--multi-value)

## Data-type → default component

| GeneralDataType | value | default component |
|-----------------|-------|-------------------|
| Guid / Text | 0,1 | `textField` |
| Date | 2 | `dateField` |
| Time | 3 | `timeField` |
| DateTime | 4 | `dateField` (showTime) |
| Boolean | 5 | `checkbox` |
| Numeric | 6 | `numberField` |
| Enum / ReferenceList | 7,8 | `dropdown` (single) |
| MultiValueReferenceList | 9 | `dropdown` (multiple, bridged) |
| EntityReference | 10 | `autocomplete` |
| StoredFile | 11 | `fileUpload` |
| List | 12 | `dropdown` |

## Input components

| type | key props (beyond base) | version |
|------|-------------------------|---------|
| `textField` | `textType:"text"` | 5 |
| `textArea` | `autoSize`, `showCount`, `allowClear` | 4 |
| `numberField` | `min`, `max`, `stepNumeric` | 4 |
| `checkbox` | — | 4 |
| `switch` | — | 3 |
| `dateField` | `picker`, `showTime`, `dateFormat`, `timeFormat`, `defaultToMidnight`, `disabledDateMode`, `range` | 5 |
| `timeField` | `format` | 4 |
| `passwordCombo` | `confirmPlaceholder`, `minLength` | 6 |
| `codeEditor` | `language`, `mode:"inline"` | 3 |
| `richTextEditor` | `toolbar`, `autoHeight` | 3 |
| `phoneNumberInput` | `valueFormat:"string"`, `defaultCountry`, `enableSearch` | 0 |

## Reference-list / entity components

`dropdown`, `checkboxGroup`, `radio` bind a reference list via
`dataSourceType:"referenceList"` + `referenceListId:{ name:"<module>.<short>", module:"<module>" }`
(the skill builds `name` from the parameter's `referenceListNamespace`/`referenceListName`).

| type | key props | version |
|------|-----------|---------|
| `dropdown` | `dataSourceType`, `useRawValues`, `referenceListId`, `mode:"single"|"multiple"`, `valueFormat:"simple"` | 7 |
| `checkboxGroup` | `dataSourceType`, `direction`, `mode`, `referenceListId` | 5 |
| `radio` | `dataSourceType`, `direction`, `referenceListId` | 6 |
| `autocomplete` | `dataSourceType:"entitiesList"`, `useRawValues:true`, `entityType`, `entityTypeShortAlias`, `entityDisplayProperty`, `mode`, `valueFormat:"entityReference"` | 8 |
| `entityPicker` | `entityType`, `mode`, `useRawValues`, `valueFormat:"entityReference"`, `items[]` (columns) | 10 |
| `entityReference` | `entityType`, `displayProperty`, `entityReferenceType:"NavigateLink"`, `formIdentifier` | 6 |

For entities the skill fills `entityType`/`entityTypeShortAlias` from `param.entityTypeShortAlias`
and the display column from `param.entityDisplayProperty` (defaults to `_displayName` if you don't
set it — but always verify that field actually resolves for the specific entity before relying on
either the default or an explicit value; see
[filter-form.md](filter-form.md#verify-entitydisplayproperty-before-trusting-it)).

## Specialised inputs

| type | key props | version |
|------|-----------|---------|
| `address` | `googleMapsApiKey`, `openCageApiKey`, `onSelectCustom` | 4 |
| `fileUpload` | `uploadMode`, `allowUpload/Replace/Delete`, `ownerType`, `ownerId` | 5 |
| `attachmentsEditor` | `listType`, `layout`, `ownerType`, `ownerId` | 7 |
| `iconPicker` | `color`, `fontSize` | 3 |

`address`/`fileUpload`/`attachmentsEditor` usually need extra config (API keys, owner) — pass
those via `param.componentProps`.

## Layout / display components

Not typically used as filters, but available via `param.component` + `componentProps`, and useful
if you assemble markup by hand: `container`, `columns`, `collapsiblePanel`, `tabs`, `wizard`,
`sectionSeparator`, `divider`, `space`, `card`, `alert`, `statusTag`, `refListStatus`, `image`,
`htmlRender`, `link`, `button`, `buttonGroup`. Containers hold children in a `components` array (or
`columns[].components` / `tabs[].components`); set each child's `parentId` to the container `id`.

## Overriding & multi-value

- **Explicit component:** `{ "name":"notes", "component":"textArea", "componentProps":{ "autoSize":true } }`.
- **componentProps** is merged last, so it wins over the defaults — use it for anything not covered.
- **Multi-value** (`multiValue:true`): the visible control is `"<name>List"` and an `onChangeCustom`
  writes the comma-joined SQL param `"<name>"`, matching the `string_split(@name,',')` SQL
  predicate. For scalar filters (dataType 8/9) that's `form.setFieldValue('<name>', value?.join(','))`;
  for **entity-reference filters (dataType 10)** the picker can hand back `{id,...}` objects even in
  multi-select mode, so `buildComponent` instead emits an id-unwrapping version — see
  [filter-form.md](filter-form.md#verify-entitydisplayproperty-before-trusting-it). Provide your own
  `onChangeCustom` in `componentProps` to override either default.
