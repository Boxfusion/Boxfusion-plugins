"""The per-package JSON catalogue -> one Excel workbook for reviewers.

    python export_workbook.py --run-dir security-audits/YYMMDD-HHMM [--out path.xlsx]

Writes `<run-dir>/security-catalog-<run>.xlsx` with one worksheet per object type: Findings,
Entities, Roles, Permissions, Custom Forms, Configured Forms, Endpoints. Every row carries the
module it came from (first column) and the catalogue file it was read from (last column).

Columns are ordered for a reviewer deciding what to do next: what the object is, the
recommended action, the access it actually has, whether anything uses it, and why the
recommendation was made. Every other field declared in `catalog_schema.py` follows in declared
order, so the columns are identical from run to run, whether or not a run populates them.
A field the catalogue holds but the schema does not declare is appended with a warning (and
`verify_run.py` fails the run), so nothing is silently dropped.

It reads the catalogue only, so run it after the review-pass rebuild - the workbook then shows
the same dispositions as the reports. It is the last step of phase 2 in `run_audit.py`.

Reviewers annotate the workbook by hand. If the target already exists and differs from what
would be written, it is kept as `<name>.bak-YYMMDD-HHMMSS.xlsx` rather than overwritten.

Stdlib only: the .xlsx is written directly as SpreadsheetML, like the rest of these scripts.
"""

import argparse
import glob
import io
import json
import os
import re
import sys
import time
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from catalog_schema import KINDS_BY_ARTIFACT, NESTED, ROWS, columns  # noqa: E402
from shesha_audit import latest_run_dir, read_json  # noqa: E402

MAX_CELL = 32000  # Excel's hard limit is 32767 characters per cell
# Very large, and restated by the flattened authorizationRules.* columns.
DROP = {"authorizationRules.entityConfigPermissions"}

# Leading columns per worksheet, in order. The rest of the kind's declared columns follow,
# then "Source File". Every name here must be a column catalog_schema.py declares - checked
# at start-up, so a renamed field fails loudly instead of quietly vanishing from the sheet.
LEAD = {
    "Findings": [
        "Module", "id", "severityHint", "status", "title", "category", "recommendationHint",
        "evidence", "reviewRequired", "reviewed", "reviewNote",
    ],
    "Entities": [
        "Module", "entity", "className", "CRUDEndpoints", "recommendedAction",
        "authorizationRules.effectiveAccessName", "unreferencedActions", "isUnreferenced",
        "recommendationBasis", "sensitivity.rating", "unreferencedWriteActions",
        "grantedToRoles", "authorizationRules.permissions", "hasGlobalSpecifications",
        "specifications", "referencedByForms", "referencedByCustomForms", "reviewed",
        "reviewNote", "reviewTheme",
    ],
    "Roles": [
        "Module", "role", "recommendedAction", "permissionCount", "permissions",
        "recommendationBasis", "holdsNoPermissions", "grantsResolved", "description",
    ],
    "Permissions": [
        "Module", "permission", "recommendedAction", "rolesAssignedTo", "isUnreferenced",
        "totalReferences", "isDbPermission", "guardsNothing", "recommendationBasis",
        "displayName", "reviewed", "reviewNote",
    ],
    "Custom Forms": [
        "Module", "file", "route", "recommendedAction", "isUnreferenced", "kind",
        "recommendationBasis", "sensitivity.rating", "isReferencedByMainMenu",
        "isReferencedByOtherForm", "referencedByCustomForms", "endPointsReferenced",
        "permissionsReferenced", "usesDataHooks",
    ],
    "Configured Forms": [
        "Module", "name", "label", "recommendedAction", "accessConfig.accessName",
        "isUnreferenced", "recommendationBasis", "sensitivity.rating", "modelType",
        "isReferencedByMainMenu", "isReferencedByOtherForm", "isReferencedByCustomForm",
        "permissionsReferenced", "endPointsReferenced", "staleEndpoints", "externalUrls",
        "reviewed", "reviewNote",
    ],
    "Endpoints": [
        "Module", "path", "methods", "recommendedAction",
        "authorizationRules.effectiveAccessName", "isWriteOperation", "isUnreferenced",
        "recommendationBasis", "observedAnonymous", "probeResults",
        "authorizationRules.permissions", "grantedToRoles", "sensitivity.rating",
        "referencedByForms", "referencedByCustomForms", "service", "action", "reviewed",
        "reviewNote",
    ],
}
SHEETS = list(LEAD)
KIND_OF_SHEET = {spec["sheet"]: kind for kind, spec in ROWS.items()}


def _check_lead():
    for sheet, lead in LEAD.items():
        declared = set(columns(KIND_OF_SHEET[sheet])) | {"Module"}
        unknown = [c for c in lead if c not in declared]
        if unknown:
            raise SystemExit("export_workbook.py: LEAD[%r] names undeclared column(s) %s"
                             % (sheet, unknown))


_check_lead()
# Columns kept in view while scrolling right: Module plus the object's name.
FREEZE_COLS = 2


# ---------------------------------------------------------------------------- rows

def cell_value(v):
    if v is None:
        return None
    if isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, list):
        if all(not isinstance(x, (dict, list)) for x in v):
            s = "; ".join(str(x) for x in v)
        elif all(isinstance(x, dict) and "url" in x for x in v):
            s = "; ".join(x["url"] for x in v)
        elif all(isinstance(x, dict) and "principal" in x for x in v):
            s = "; ".join(("%s: %s %s" % (x.get("principal"), x.get("status"),
                                          x.get("verdict", ""))).strip() for x in v)
        else:
            s = json.dumps(v, ensure_ascii=False)
    elif isinstance(v, dict):
        # crudActions: {"create": {"url": ..., "referenced": bool}, ...}
        if v and all(isinstance(x, dict) and "url" in x for x in v.values()):
            s = "; ".join(k + ("" if x.get("referenced", True) else " (unreferenced)")
                          for k, x in v.items())
        else:
            s = json.dumps(v, ensure_ascii=False)
    else:
        s = str(v)
    return s[:MAX_CELL] if s else None


def flatten(kind, record):
    out = {}
    for k, v in record.items():
        if (kind, k) in NESTED:
            # a null parent (accessConfig with no record) leaves its columns empty
            for sub, sv in (v or {}).items():
                if "%s.%s" % (k, sub) not in DROP:
                    out["%s.%s" % (k, sub)] = cell_value(sv)
        elif k not in DROP:
            out[k] = cell_value(v)
    return out


def collect(catalog_dir):
    sheets = {name: [] for name in SHEETS}
    for path in sorted(glob.glob(os.path.join(catalog_dir, "*.json"))):
        name = os.path.basename(path)
        if name in ("_index.json", "review-overrides.json"):
            continue
        doc = read_json(path)
        package = doc.get("package")
        for kind in KINDS_BY_ARTIFACT.get(doc.get("artifact"), []):
            spec = ROWS[kind]
            for record in doc.get(spec["list"]) or []:
                row = {"Module": record.get("module") or record.get("package") or package}
                row.update((k, v) for k, v in flatten(kind, record).items() if k != "module")
                sheet = spec["sheet"]
                row["Source File"] = name
                sheets[sheet].append(row)
    return sheets


def columns_for(sheet, rows, warn=False):
    """Fixed columns from the schema; the rows only matter if they hold something undeclared."""
    declared = [c for c in columns(KIND_OF_SHEET[sheet], DROP) if c != "module"]
    lead = LEAD[sheet]
    fixed = lead + [c for c in declared if c not in lead] + ["Source File"]
    extra = []
    for row in rows:
        for k in row:
            if k not in fixed and k not in extra:
                extra.append(k)
    if extra and warn:
        print("WARNING: %s holds undeclared field(s) %s - appended; declare them in "
              "catalog_schema.py" % (sheet, ", ".join(extra)), file=sys.stderr)
    return fixed[:-1] + extra + fixed[-1:]


# ---------------------------------------------------------------------------- xlsx

ILLEGAL = re.compile(u"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def col_letter(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def xml_cell(ref, v, style=0):
    st = ' s="%d"' % style if style else ""
    if isinstance(v, bool):
        return '<c r="%s" t="b"%s><v>%d</v></c>' % (ref, st, int(v))
    if isinstance(v, (int, float)):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, st, v)
    text = escape(ILLEGAL.sub("", str(v)))
    return '<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>' % (
        ref, st, text)


def sheet_xml(sheet, cols, rows):
    last = col_letter(len(cols))
    freeze = FREEZE_COLS
    widths = []
    for c in cols:
        w = max([len(c)] + [len(str(r.get(c) if r.get(c) is not None else ""))
                            for r in rows[:500]])
        widths.append(min(max(w + 2, 10), 60))
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        '<dimension ref="A1:%s%d"/>' % (last, len(rows) + 1),
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane xSplit="%d" ySplit="1" topLeftCell="%s2" activePane="bottomRight" '
        'state="frozen"/></sheetView></sheetViews>' % (freeze, col_letter(freeze + 1)),
        '<cols>%s</cols>' % "".join('<col min="%d" max="%d" width="%d" customWidth="1"/>'
                                    % (i, i, w) for i, w in enumerate(widths, 1)),
        '<sheetData>',
        '<row r="1">%s</row>' % "".join(xml_cell("%s1" % col_letter(i), c, 1)
                                         for i, c in enumerate(cols, 1)),
    ]
    for n, row in enumerate(rows, 2):
        cells = "".join(xml_cell("%s%d" % (col_letter(i), n), row[c])
                        for i, c in enumerate(cols, 1) if row.get(c) is not None)
        parts.append('<row r="%d">%s</row>' % (n, cells))
    parts.append('</sheetData>')
    if rows:
        parts.append('<autoFilter ref="A1:%s%d"/>' % (last, len(rows) + 1))
    parts.append('</worksheet>')
    return "".join(parts)


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/></patternFill></fill>'
    '</fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
    '</cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" '
    'applyFill="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>')


def build_xlsx(sheets):
    """Return the workbook as bytes. Deterministic, so an unchanged catalogue gives an
    identical file - which is how a hand-edited copy is told apart from a stale one."""
    names = list(SHEETS)
    files = {}
    files["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/'
                  'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % i
                  for i in range(1, len(names) + 1))
        + '</Types>')
    files["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    defined = []
    for i, name in enumerate(names):
        rows = sheets[name]
        if rows:
            last = col_letter(len(columns_for(name, rows)))
            defined.append('<definedName name="_xlnm._FilterDatabase" localSheetId="%d" '
                           'hidden="1">\'%s\'!$A$1:$%s$%d</definedName>'
                           % (i, escape(name), last, len(rows) + 1))
    files["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>%s</sheets>' % "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>'
                                        % (escape(n), i, i)
                                        for i, n in enumerate(names, 1))
        + ('<definedNames>%s</definedNames>' % "".join(defined) if defined else "")
        + '</workbook>')
    files["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/'
                  'officeDocument/2006/relationships/worksheet" '
                  'Target="worksheets/sheet%d.xml"/>' % (i, i)
                  for i in range(1, len(names) + 1))
        + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/'
          '2006/relationships/styles" Target="styles.xml"/>' % (len(names) + 1)
        + '</Relationships>')
    files["xl/styles.xml"] = STYLES
    for i, name in enumerate(names, 1):
        rows = sheets[name]
        files["xl/worksheets/sheet%d.xml" % i] = sheet_xml(name, columns_for(name, rows, True),
                                                           rows)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in files.items():
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode("utf-8"))
    return buf.getvalue()


# ---------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", help="run directory (default: the latest)")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--out", help="output path (default: <run-dir>/security-catalog-<run>.xlsx)")
    ap.add_argument("--url", help=argparse.SUPPRESS)  # accepted so run_audit.py can pass it
    a = ap.parse_args()

    run_dir = a.run_dir or latest_run_dir(a.repo_root)
    if not run_dir:
        print("No run directory. Pass --run-dir.", file=sys.stderr)
        return 1
    catalog = os.path.join(run_dir, "catalog")
    if not os.path.isfile(os.path.join(catalog, "_index.json")):
        print("No catalogue in %s - run build_catalogs.py first." % catalog, file=sys.stderr)
        return 1
    out = a.out or os.path.join(
        run_dir, "security-catalog-%s.xlsx" % os.path.basename(os.path.normpath(run_dir)))

    sheets = collect(catalog)
    data = build_xlsx(sheets)

    if os.path.isfile(out):
        with open(out, "rb") as fh:
            current = fh.read()
        if current == data:
            print("%s is up to date" % out)
            return 0
        root, ext = os.path.splitext(out)
        backup = "%s.bak-%s%s" % (root, time.strftime("%y%m%d-%H%M%S"), ext)
        os.replace(out, backup)
        print("kept the previous workbook (hand-edited or older catalogue) as %s" % backup)

    with open(out, "wb") as fh:
        fh.write(data)
    for name in SHEETS:
        print("  %-18s %5d rows" % (name, len(sheets[name])))
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
