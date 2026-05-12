# Generate Component Properties Index

This document contains the extraction script used in **Step 1** of the `clean-form-config` skill.

---

## When to run

Run whenever `.claude/shesha/component-properties.json` is:
- **Missing** from the project.
- In **v1 format** (`_baseProperties` key present instead of `_meta`).
- **Stale** after a shesha-reactjs upgrade (delete the file to force regeneration).

---

## Setup

```bash
mkdir -p .claude/shesha
```

Write the script below to `.claude/shesha/generate-component-props.mjs`, then run it using one of these two paths:

**Option A — project already has shesha-reactjs locally** (CWD contains `src/designer-components/`):
```bash
node .claude/shesha/generate-component-props.mjs
```

**Option B — fetch from GitHub** (no local shesha-reactjs):
```bash
mkdir -p .claude/shesha/_shesha-tmp
cd .claude/shesha/_shesha-tmp
git init
git remote add origin https://github.com/shesha-io/shesha-reactjs.git
git sparse-checkout init --cone
git sparse-checkout set src/designer-components
git pull --depth=1 origin main
cd -
node .claude/shesha/generate-component-props.mjs --root=.claude/shesha/_shesha-tmp
rm -rf .claude/shesha/_shesha-tmp
```

If the script exits with `ERROR: src/designer-components/ not found`, the sparse clone likely failed — check network access to GitHub and retry Option B.

---

## Script

```javascript
import { readFileSync, readdirSync, statSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname, resolve } from 'path';

const CWD = process.cwd();
const rootArg = process.argv.find(a => a.startsWith('--root='));
const ROOT = rootArg ? resolve(rootArg.replace('--root=', '')) : CWD;
const DESIGNER_COMPONENTS_DIR = resolve(ROOT, 'src/designer-components');
const OUTPUT_DIR = resolve(CWD, '.claude/shesha');
const OUTPUT_FILE = resolve(OUTPUT_DIR, 'component-properties.json');

if (!existsSync(DESIGNER_COMPONENTS_DIR)) {
  console.error(`ERROR: src/designer-components/ not found at ${DESIGNER_COMPONENTS_DIR}`);
  console.error('Run with --root=<path-to-shesha-reactjs> or use the GitHub sparse-clone approach in generate-index.md.');
  process.exit(1);
}

mkdirSync(OUTPUT_DIR, { recursive: true });

const BASE_PROPERTY_DEFS = [
  { name: 'hideLabel', type: 'boolean' }, { name: 'hidden', type: 'boolean' },
  { name: 'readOnly', type: 'boolean' }, { name: 'isDynamic', type: 'boolean' },
  { name: 'jsSetting', type: 'boolean' }, { name: 'autoWidth', type: 'boolean' },
  { name: 'autoHeight', type: 'boolean' }, { name: 'hideScrollBar', type: 'boolean' },
  { name: 'enableStyleOnReadonly', type: 'boolean' }, { name: 'noLabelAutoMargin', type: 'boolean' },
  { name: 'block', type: 'boolean' }, { name: 'hideBorder', type: 'boolean' },
  { name: 'id', type: 'string' }, { name: 'type', type: 'string' },
  { name: 'parentId', type: 'string' }, { name: 'componentName', type: 'string' },
  { name: 'propertyName', type: 'string' }, { name: 'context', type: 'string' },
  { name: 'initialContext', type: 'string' }, { name: 'label', type: 'string' },
  { name: 'labelAlign', type: 'string' }, { name: 'customVisibility', type: 'string' },
  { name: 'onBlurCustom', type: 'string' }, { name: 'onChangeCustom', type: 'string' },
  { name: 'onClickCustom', type: 'string' }, { name: 'onFocusCustom', type: 'string' },
  { name: 'onSelectCustom', type: 'string' }, { name: 'customEnabled', type: 'string' },
  { name: 'style', type: 'string' }, { name: 'stylingBox', type: 'string' },
  { name: 'wrapperStyle', type: 'string' }, { name: 'className', type: 'string' },
  { name: 'editMode', type: 'string' }, { name: 'size', type: 'string' },
  { name: 'noDataText', type: 'string' }, { name: 'noDataIcon', type: 'string' },
  { name: 'noDataSecondaryText', type: 'string' }, { name: 'listType', type: 'string' },
  { name: 'version', type: 'number' },
  { name: 'validate', type: 'object' }, { name: 'border', type: 'object' },
  { name: 'background', type: 'object' }, { name: 'font', type: 'object' },
  { name: 'shadow', type: 'object' }, { name: 'menuItemShadow', type: 'object' },
  { name: 'dimensions', type: 'object' }, { name: 'inputStyles', type: 'object' },
  { name: 'allStyles', type: 'object' },
  { name: 'permissions', type: 'array' }, { name: '_formFields', type: 'array' },
  { name: 'subscribedEventNames', type: 'array' },
  { name: 'queryParams', type: 'skip' }, { name: 'overflow', type: 'skip' },
  { name: 'tooltip', type: 'skip' }, { name: 'defaultValue', type: 'skip' },
  { name: 'placeholder', type: 'skip' }, { name: 'description', type: 'skip' },
  { name: 'layout', type: 'skip' }, { name: 'color', type: 'skip' },
  { name: 'desktop', type: 'skip' }, { name: 'tablet', type: 'skip' }, { name: 'mobile', type: 'skip' },
  { name: 'borderSize', type: 'skip' }, { name: 'borderRadius', type: 'skip' },
  { name: 'borderType', type: 'skip' }, { name: 'borderStyle', type: 'skip' },
  { name: 'borderWidth', type: 'skip' }, { name: 'borderColor', type: 'skip' },
  { name: 'fontColor', type: 'skip' }, { name: 'fontWeight', type: 'skip' },
  { name: 'fontSize', type: 'skip' }, { name: 'height', type: 'skip' }, { name: 'width', type: 'skip' },
  { name: 'backgroundColor', type: 'skip' }, { name: 'backgroundPosition', type: 'skip' },
  { name: 'backgroundCover', type: 'skip' }, { name: 'backgroundRepeat', type: 'skip' },
  { name: 'backgroundType', type: 'skip' }, { name: 'backgroundDataSource', type: 'skip' },
  { name: 'backgroundUrl', type: 'skip' }, { name: 'backgroundBase64', type: 'skip' },
  { name: 'backgroundStoredFileId', type: 'skip' },
  { name: 'primaryTextColor', type: 'skip' }, { name: 'primaryBgColor', type: 'skip' },
  { name: 'secondaryBgColor', type: 'skip' }, { name: 'secondaryTextColor', type: 'skip' },
  { name: 'components', type: 'skip' }, { name: 'settingsValidationErrors', type: 'skip' },
  { name: 'injectedTableRow', type: 'skip' }, { name: 'injectedDefaultValue', type: 'skip' },
];

const BASE_PROPERTIES = BASE_PROPERTY_DEFS.map(d => d.name);
const baseSet = new Set(BASE_PROPERTIES);

const METHOD_TYPE_MAP = {
  checkbox: 'boolean', switch: 'boolean', labelConfigurator: 'boolean',
  numberField: 'number', slider: 'number',
  textField: 'string', textArea: 'string', codeEditor: 'string', colorPicker: 'string',
  iconPicker: 'string', propertyAutocomplete: 'string', contextPropertyAutocomplete: 'string',
  entityTypeAutocomplete: 'string', endpointsAutocomplete: 'string', formAutocomplete: 'string',
  permissionAutocomplete: 'string', referenceListAutocomplete: 'string',
  dateField: 'string', timePicker: 'string', link: 'string', editModeSelector: 'string', radio: 'string',
  editableTagGroup: 'array', buttons: 'array',
  queryBuilder: 'object', styleBox: 'object', configurableActionConfigurator: 'object', labelValueEditor: 'object',
  dropdown: 'skip', autocomplete: 'skip', fileUpload: 'skip',
  container: 'skip', columns: 'skip', tabs: 'skip', searchableTabs: 'skip',
  collapsiblePanel: 'skip', sectionSeparator: 'skip', alert: 'skip',
  propertyRouter: 'skip', settingsInput: 'skip', settingsInputRow: 'skip',
  text: 'skip', keyInformationBar: 'skip', dataContext: 'skip',
};

const SETTINGS_INPUT_TYPE_MAP = {
  switch: 'boolean', threeStateSwitch: 'boolean',
  numberField: 'number', slider: 'number',
  textField: 'string', textArea: 'string', codeEditor: 'string', colorPicker: 'string',
  iconPicker: 'string', propertyAutocomplete: 'string', contextPropertyAutocomplete: 'string',
  entityTypeAutocomplete: 'string', endpointsAutocomplete: 'string', formAutocomplete: 'string',
  permissionAutocomplete: 'string', referenceListAutocomplete: 'string',
  radio: 'string', editModeSelector: 'string', dateField: 'string', date: 'string',
  dropdown: 'skip', autocomplete: 'skip', permissions: 'skip',
  queryBuilder: 'object', configurableActionConfigurator: 'object', labelValueEditor: 'object',
  editableTagGroup: 'array',
};

const UI_CONTAINER_EXACT = new Set([
  'settingsTabs', 'propertyRouter1', 'propertyRouter2', 'propertyRouter3', 'styleRouter1', 'styleRouter2',
]);

function isUIContainer(name) {
  if (UI_CONTAINER_EXACT.has(name)) return true;
  if (/^pnl[A-Z]/.test(name)) return true;
  if (/^(propertyRouter|styleRouter)\d*$/.test(name)) return true;
  if (/^(container|panel|tab|group)\d+$/.test(name)) return true;
  return false;
}

function topLevelKey(p) { return p.split('.')[0]; }

function walkDir(dir) {
  const results = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) results.push(...walkDir(full));
    else results.push(full);
  }
  return results;
}

function findSettingsFile(dir) {
  for (const c of ['settingsForm.ts','settingsForm.tsx','settings.ts','settings.tsx','formSettings.ts','formSettings.tsx']) {
    const p = join(dir, c);
    if (existsSync(p)) return p;
  }
  return null;
}

function extractPropertyNames(filePath) {
  const source = readFileSync(filePath, 'utf-8');
  const props = new Map();
  const re = /propertyName:\s+['"]([^'"]+)['"]/g;
  let m;
  while ((m = re.exec(source)) !== null) {
    const raw = m[1];
    const top = topLevelKey(raw);
    if (isUIContainer(top) || isUIContainer(raw)) continue;
    const lookback = source.slice(Math.max(0, m.index - 300), m.index);
    const builderRe = /\.add([A-Z][a-zA-Z]+)\s*\(/g;
    let bm; let lastBm = null;
    while ((bm = builderRe.exec(lookback)) !== null) lastBm = bm;
    let resolvedType = 'skip';
    if (lastBm) {
      const camelKey = lastBm[1].charAt(0).toLowerCase() + lastBm[1].slice(1);
      if (camelKey === 'settingsInput' || camelKey === 'settingsInputRow') {
        const win = source.slice(Math.max(0, m.index - 150), m.index + 150);
        const itMatch = win.match(/\binputType:\s+['"]([^'"]+)['"]/) || win.match(/\btype:\s+['"]([^'"]+)['"]/);
        resolvedType = itMatch ? (SETTINGS_INPUT_TYPE_MAP[itMatch[1]] || 'skip') : 'skip';
      } else {
        resolvedType = METHOD_TYPE_MAP[camelKey] || 'skip';
      }
    }
    if (!props.has(top) || props.get(top) === 'skip') props.set(top, resolvedType);
  }
  return [...props.entries()].map(([name, type]) => ({ name, type })).sort((a, b) => a.name.localeCompare(b.name));
}

const allFiles = walkDir(DESIGNER_COMPONENTS_DIR);
const typeToFolder = new Map();
const TYPE_RE = /\btype:\s+['"]([a-zA-Z][a-zA-Z0-9._-]*)['"](?:,|\s)/g;
const SKIP_TYPES = new Set([
  'string','number','boolean','object','any','void','never','unknown','null','undefined','symbol','bigint',
  'function','constructor','class','module',
  'color','password','email','tel','url','search','submit','reset','file','range','date','time','month','week',
]);
const LEGIT_AMBIGUOUS = new Set(['text','button','checkbox','radio','image','hidden']);

for (const file of allFiles) {
  if (!file.endsWith('.ts') && !file.endsWith('.tsx')) continue;
  const base = file.split(/[/\\]/).pop();
  if (base.startsWith('settings') || base.includes('.test.') || base.includes('.spec.') ||
      base.includes('migrat') || ['interfaces.ts','utils.ts','utils.tsx','styles.ts','styles.tsx','models.ts','model.ts'].includes(base)) continue;
  const source = readFileSync(file, 'utf-8');
  if (!/\bname:\s+['"][^'"]{2,}['"]/.test(source)) continue;
  TYPE_RE.lastIndex = 0;
  let m;
  while ((m = TYPE_RE.exec(source)) !== null) {
    const type = m[1];
    if (SKIP_TYPES.has(type) && !LEGIT_AMBIGUOUS.has(type)) continue;
    const win = source.slice(Math.max(0, m.index - 300), m.index + 300);
    if (!/\bname:\s+['"][^'"]{2,}['"]/.test(win)) continue;
    if (LEGIT_AMBIGUOUS.has(type)) {
      const baseName = base.replace(/\.(ts|tsx)$/, '').toLowerCase();
      if (baseName !== type.toLowerCase() && baseName !== 'index' && !baseName.includes(type.toLowerCase())) continue;
    }
    const folder = dirname(file);
    const existing = typeToFolder.get(type);
    if (!existing || folder.length < existing.length) typeToFolder.set(type, folder);
  }
}

const componentMap = {};
for (const [type, folder] of typeToFolder.entries()) {
  if (['root','settingsInput','settingsInputRow','searchableTabs'].includes(type)) continue;
  const sf = findSettingsFile(folder) || findSettingsFile(dirname(folder));
  if (!sf) { componentMap[type] = { props: [], types: {} }; continue; }
  const propDefs = extractPropertyNames(sf).filter(d => !baseSet.has(d.name));
  componentMap[type] = {
    props: propDefs.map(d => d.name),
    types: Object.fromEntries(propDefs.filter(d => d.type !== 'skip').map(d => [d.name, d.type])),
  };
}

const FORM_SETTINGS_DEFS = [
  { name: 'modelType', type: 'skip' }, { name: 'layout', type: 'string' },
  { name: 'colon', type: 'boolean' }, { name: 'labelCol', type: 'object' },
  { name: 'wrapperCol', type: 'object' }, { name: 'size', type: 'string' },
  { name: 'isSettingsForm', type: 'boolean' }, { name: 'permissions', type: 'array' },
  { name: 'access', type: 'skip' }, { name: 'version', type: 'number' },
  { name: 'fieldsToFetch', type: 'array' }, { name: 'excludeFormFieldsInPayload', type: 'string' },
  { name: 'postUrl', type: 'string' }, { name: 'putUrl', type: 'string' },
  { name: 'deleteUrl', type: 'string' }, { name: 'getUrl', type: 'string' },
  { name: 'initialValues', type: 'array' }, { name: 'preparedValues', type: 'string' },
  { name: 'onInitialized', type: 'string' }, { name: 'onDataLoaded', type: 'string' },
  { name: 'onUpdate', type: 'string' }, { name: 'dataLoaderType', type: 'string' },
  { name: 'dataLoadersSettings', type: 'object' }, { name: 'dataSubmitterType', type: 'string' },
  { name: 'dataSubmittersSettings', type: 'object' }, { name: 'onBeforeDataLoad', type: 'string' },
  { name: 'onAfterDataLoad', type: 'string' }, { name: 'onValuesUpdate', type: 'string' },
  { name: 'onPrepareSubmitData', type: 'string' }, { name: 'onBeforeSubmit', type: 'string' },
  { name: 'onSubmitSuccess', type: 'string' }, { name: 'onSubmitFailed', type: 'string' },
];

const baseTypes = Object.fromEntries(BASE_PROPERTY_DEFS.filter(d => d.type !== 'skip').map(d => [d.name, d.type]));
const formSettingsTypes = Object.fromEntries(FORM_SETTINGS_DEFS.filter(d => d.type !== 'skip').map(d => [d.name, d.type]));

writeFileSync(OUTPUT_FILE, JSON.stringify({
  _meta: { version: 2, generated: new Date().toISOString(), componentCount: Object.keys(componentMap).length },
  base: { props: [...BASE_PROPERTIES].sort(), types: baseTypes },
  _formSettings: { props: FORM_SETTINGS_DEFS.map(d => d.name).sort(), types: formSettingsTypes },
  ...Object.fromEntries(Object.entries(componentMap).sort(([a],[b]) => a.localeCompare(b))),
}, null, 2), 'utf-8');

console.log(`Generated ${OUTPUT_FILE} with ${Object.keys(componentMap).length} component types (v2 format)`);
```

---

## Output format (v2)

```json
{
  "_meta": { "version": 2, "generated": "...", "componentCount": 113 },
  "base": {
    "props": ["id", "type", "hidden", ...],
    "types": { "id": "string", "hidden": "boolean", "validate": "object" }
  },
  "_formSettings": {
    "props": ["colon", "dataLoaderType", ...],
    "types": { "colon": "boolean", "dataLoaderType": "string" }
  },
  "textField": {
    "props": ["prefix", "spellCheck", ...],
    "types": { "prefix": "string", "spellCheck": "boolean" }
  }
}
```

Properties with ambiguous/union types appear in `props` but are omitted from `types` — type-checking is skipped for those.
