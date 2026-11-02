"""The catalogue's row format, declared once.

Imported, not run. Three scripts read this so they cannot drift apart:

- `build_catalogs.py` passes every row list through `normalise_rows()` before writing, so each
  row carries every field, in declared order, with a default where the builder set nothing,
  and each list is sorted by its natural key.
- `export_workbook.py` builds each worksheet's columns from `columns()`, so a column is always
  present, in the same place, even when every row leaves it empty.
- `verify_run.py` calls `check_document()`, which FAILs a run whose rows or headers differ from
  this declaration in fields, order or type.

Before this existed, fields such as `reviewed`, `reviewNote` and `observedAnonymous` appeared
only on the rows they applied to. The JSON therefore changed shape from run to run, and the
workbook's columns changed with it.

Changing the format means changing it here. Add the field to `ROWS` (or `NESTED`), then
update `references/catalog-schemas.md`, and set the builder to populate it. A field the
builder writes that is not declared here is kept at the end of its row, so no data is lost,
but `verify_run.py` fails the run until it is declared.

Types: s str, b bool, i int, l list, d dict. A trailing `?` allows null. Fields taken
straight from live configuration are nullable, because the framework does not guarantee them.
"""

import re

# kind -> artifact, the list key inside the artifact, the sort key, and the ordered fields as
# (name, type, default). A default is used only when the builder left the field out.
ROWS = {
    "findings": {
        "artifact": "other-findings", "list": "findings", "sheet": "Findings",
        "sort": "id",
        "fields": [
            ("id", "s", None), ("category", "s", None), ("title", "s", None),
            ("severityHint", "s", None), ("status", "s", None), ("evidence", "l", []),
            ("recommendationHint", "s", None), ("reviewRequired", "b", True),
            ("reviewed", "b", False), ("reviewNote", "s?", None),
        ],
    },
    "entities": {
        "artifact": "entities", "list": "entities", "sheet": "Entities", "sort": "entity",
        "fields": [
            ("entity", "s", None), ("className", "s?", None), ("module", "s", None),
            ("attributedBy", "s", None), ("owner", "s", None), ("tableName", "s?", None),
            ("generateAppService", "b?", None),
            ("declaredDisableGenerateApplicationService", "b", False),
            ("CRUDEndpoints", "s", ""), ("crudActions", "d", {}),
            ("unreferencedActions", "l", []), ("unreferencedWriteActions", "l", []),
            ("isUnreferenced", "b", False), ("referencedByForms", "l", []),
            ("referencedByCustomForms", "l", []), ("referenceIndeterminate", "b", False),
            ("packageSourcesNotScanned", "l", []),
            ("backendCodeReferences", "i", 0), ("backendCodeFiles", "l", []),
            ("hasPermissionedObjectConfig", "b", False), ("authorizationRules", "d", None),
            ("authorizationMethod", "s", None), ("grantedToRoles", "l", []),
            ("hasGlobalSpecifications", "b", False), ("specifications", "l", []),
            ("sensitivity", "d", None), ("recommendedAction", "s", None),
            ("recommendationBasis", "s?", None), ("reviewTheme", "s?", None),
            ("reviewed", "b", False), ("reviewNote", "s?", None),
        ],
    },
    "roles": {
        "artifact": "roles-and-permissions", "list": "roles", "sheet": "Roles", "sort": "role",
        "fields": [
            ("role", "s", None), ("id", "s?", None), ("module", "s", None),
            ("description", "s?", None), ("permissions", "l", []),
            ("permissionCount", "i", 0), ("grantsResolved", "b", False),
            ("holdsNoPermissions", "b", False), ("recommendedAction", "s", None),
            ("recommendationBasis", "s?", None),
        ],
    },
    "permissions": {
        "artifact": "roles-and-permissions", "list": "permissions", "sheet": "Permissions",
        "sort": "permission",
        "fields": [
            ("permission", "s", None), ("displayName", "s?", None), ("module", "s", None),
            ("owner", "s", None), ("isDbPermission", "b?", None), ("parentName", "s?", None),
            ("isUnreferenced", "b", False), ("guardsNothing", "b", False),
            ("rolesAssignedTo", "l", []), ("totalReferences", "i", 0),
            ("recommendedAction", "s", None), ("recommendationBasis", "s?", None),
            ("numReferencesByFormConfig", "i", 0), ("numReferencesByWebApiConfig", "i", 0),
            ("numReferencesByEntityConfig", "i", 0), ("numReferencesByAppServiceCode", "i", 0),
            ("numReferencesBySpecificationCode", "i", 0),
            ("numReferencesByOtherBackendCode", "i", 0), ("numReferencesByCustomForm", "i", 0),
            ("reviewed", "b", False), ("reviewNote", "s?", None),
        ],
    },
    "customForms": {
        "artifact": "custom-forms", "list": "forms", "sheet": "Custom Forms", "sort": "file",
        "fields": [
            ("file", "s", None), ("frontend", "s", None), ("package", "s", None),
            ("kind", "s", None), ("route", "s?", None), ("owner", "s", None),
            ("isUnreferenced", "b", False), ("isReferencedByMainMenu", "b", False),
            ("isReferencedByOtherForm", "b", False), ("referencedByCustomForms", "l", []),
            ("endPointsReferenced", "l", []), ("formsReferenced", "l", []),
            ("entitiesReferenced", "l", []), ("permissionsReferenced", "l", []),
            ("routesDeclared", "l", []), ("usesDataHooks", "b", False),
            ("sensitivity", "d", None), ("recommendedAction", "s", None),
            ("recommendationBasis", "s?", None), ("reviewed", "b", False),
            ("reviewNote", "s?", None),
        ],
    },
    "forms": {
        "artifact": "configured-forms", "list": "forms", "sheet": "Configured Forms",
        "sort": "form",
        "fields": [
            ("form", "s", None), ("module", "s", None), ("name", "s", None),
            ("label", "s?", None), ("modelType", "s?", None), ("owner", "s", None),
            ("isUnreferenced", "b", False), ("isReferencedByMainMenu", "b", False),
            ("isReferencedByOtherForm", "b", False), ("isReferencedByCustomForm", "b", False),
            ("referencedByForms", "l", []), ("referencedByCustomForms", "l", []),
            ("referencedByPackageSource", "l", []), ("packageSourcesNotScanned", "l", []),
            ("endPointsReferenced", "l", []), ("formsReferenced", "l", []),
            ("entitiesReferenced", "l", []), ("referenceListsReferenced", "l", []),
            ("ownerBindings", "l", []), ("permissionsReferenced", "l", []),
            ("staleEndpoints", "l", []), ("externalUrls", "l", []),
            # null means the form has no PermissionedObject record of its own
            ("accessConfig", "d?", None),
            ("hasPermissionedObjectConfig", "b", False), ("sensitivity", "d", None),
            ("recommendedAction", "s", None), ("recommendationBasis", "s?", None),
            ("reviewed", "b", False), ("reviewNote", "s?", None),
        ],
    },
    "endpoints": {
        "artifact": "endpoints", "list": "endpoints", "sheet": "Endpoints", "sort": "path",
        "fields": [
            ("path", "s", None), ("matchKey", "s", None), ("attributedBy", "s", None),
            ("methods", "l", []), ("service", "s", None), ("action", "s", None),
            ("owner", "s", None), ("module", "s", None), ("isWriteOperation", "b", False),
            ("isUnreferenced", "b", False), ("referencedBy", "l", []),
            ("referencedByForms", "l", []), ("referencedByCustomForms", "l", []),
            ("referencedByPackageSource", "l", []),
            ("referenceIndeterminate", "b", False), ("packageSourcesNotScanned", "l", []),
            ("hasPermissionedObjectConfig", "b", False), ("authorizationRules", "d", None),
            ("authorizationMethod", "s", None), ("grantedToRoles", "l", []),
            ("hasGlobalSpecifications", "b?", None), ("specificationEntity", "s?", None),
            ("backendCodeReferences", "i", 0), ("backendCodeFiles", "l", []),
            ("packageBackendCodeReferences", "i", 0), ("packageBackendCodeFiles", "l", []),
            ("probeResults", "l", []),
            # true only when a live anonymous probe reached an endpoint configured as closed
            ("observedAnonymous", "b", False),
            ("sensitivity", "d", None), ("recommendedAction", "s", None),
            ("recommendationBasis", "s?", None), ("reviewed", "b", False),
            ("reviewNote", "s?", None),
        ],
    },
}

SENSITIVITY = [("rating", "s", None), ("basis", "s?", None), ("reviewRequired", "b", True)]

# (kind, field) -> ordered sub-fields of an object-valued field. A nullable parent (d?) is
# either null or carries exactly these sub-fields.
NESTED = {
    ("entities", "authorizationRules"): [
        ("effectiveAccess", "i?", None), ("effectiveAccessName", "s", None),
        ("permissions", "l", []), ("resolvedVia", "s", None), ("hardcoded", "b?", None),
        # per-action PermissionedObject records, when the entity has them
        ("perAction", "d?", None),
        # permissions declared on the EntityConfig, when there are any
        ("entityConfigPermissions", "d?", None),
    ],
    ("endpoints", "authorizationRules"): [
        ("effectiveAccess", "i?", None), ("effectiveAccessName", "s", None),
        ("permissions", "l", []), ("recordAccess", "i?", None), ("hardcoded", "b?", None),
        ("resolvedVia", "s", None), ("codeAttributes", "l", []),
        # the configured access, kept when a live anonymous probe overrode it
        ("effectiveAccessBeforeProbe", "s?", None),
    ],
    ("forms", "accessConfig"): [
        ("access", "i?", None), ("accessName", "s", None), ("permissions", "l", []),
        ("hardcoded", "b?", None),
    ],
}
for _kind in ("entities", "customForms", "forms", "endpoints"):
    NESTED[(_kind, "sensitivity")] = SENSITIVITY

# Document-level fields, in order, shared by every artefact, then per artefact.
HEADER = ["generated", "backend", "defaultEndpointAccess", "defaultEndpointAccessName",
          "definitions", "inputsMissing", "package", "artifact"]
ARTIFACT_HEADER = {
    "roles-and-permissions": ["roleCount", "permissionCount", "unreferencedPermissions",
                              "roles", "permissions"],
    "configured-forms": ["formCount", "unreferenced", "anonymous", "forms"],
    "custom-forms": ["fileCount", "routes", "unreferenced", "forms"],
    "endpoints": ["endpointCount", "anonymous", "anyAuthenticated", "permissioned",
                  "unreferenced", "note", "endpoints"],
    "entities": ["entityCount", "withCrudEndpoints", "anonymous", "unreferenced",
                 "withoutGlobalSpecification", "entities"],
    "other-findings": ["findingCount", "bySeverityHint", "findings"],
}

KINDS_BY_ARTIFACT = {}
for _kind, _spec in ROWS.items():
    KINDS_BY_ARTIFACT.setdefault(_spec["artifact"], []).append(_kind)

_TYPES = {"s": str, "l": list, "d": dict, "i": int, "b": bool}


# ---------------------------------------------------------------------------- normalise

def _copy(default):
    return type(default)() if isinstance(default, (list, dict)) else default


def _ordered(obj, fields):
    out = {}
    for name, _type, default in fields:
        out[name] = obj[name] if name in obj else _copy(default)
    for name, value in obj.items():  # undeclared: kept, and flagged by check_document
        if name not in out:
            out[name] = value
    return out


def _natural(value):
    """Sort key that puts ANO-2 before ANO-10."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", "" if value is None else str(value))]


def normalise_row(kind, row):
    out = _ordered(row, ROWS[kind]["fields"])
    for (k, field), sub in NESTED.items():
        if k == kind and isinstance(out.get(field), dict):
            out[field] = _ordered(out[field], sub)
    return out


def normalise_rows(kind, rows):
    """Every field present in declared order, then sorted by the kind's natural key."""
    key = ROWS[kind]["sort"]
    return sorted((normalise_row(kind, r) for r in rows or []),
                  key=lambda r: _natural(r.get(key)))


# ---------------------------------------------------------------------------- columns

def columns(kind, drop=()):
    """Flattened column names for one kind, in declared order: nested objects expand to
    `parent.child`. Used by the workbook so its columns never depend on the data."""
    out = []
    for name, _type, _default in ROWS[kind]["fields"]:
        sub = NESTED.get((kind, name))
        if sub:
            out.extend("%s.%s" % (name, s) for s, _t, _d in sub
                       if "%s.%s" % (name, s) not in drop)
        elif name not in drop:
            out.append(name)
    return out


# ---------------------------------------------------------------------------- check

def _type_ok(value, spec):
    if value is None:
        return spec.endswith("?")
    expected = _TYPES[spec.rstrip("?")]
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def _check_fields(obj, fields, where, problems):
    names = [f[0] for f in fields]
    actual = list(obj)
    missing = [n for n in names if n not in obj]
    extra = [n for n in actual if n not in names]
    if missing:
        problems.append("%s: missing %s" % (where, ", ".join(missing)))
    if extra:
        problems.append("%s: undeclared %s - declare in catalog_schema.py"
                        % (where, ", ".join(extra)))
    if not missing and not extra and actual != names:
        problems.append("%s: fields out of declared order" % where)
    for name, spec, _default in fields:
        if name in obj and not _type_ok(obj[name], spec):
            problems.append("%s.%s: expected %s, got %s"
                            % (where, name, spec, type(obj[name]).__name__))


def check_document(name, doc):
    """Problems with one catalogue file, as strings. Empty means it matches the schema."""
    problems = []
    artifact = doc.get("artifact")
    if artifact not in ARTIFACT_HEADER:
        return ["%s: unknown artifact %r" % (name, artifact)]
    expected_header = HEADER + ARTIFACT_HEADER[artifact]
    if list(doc) != expected_header:
        problems.append("%s: header fields %s, expected %s"
                        % (name, list(doc), expected_header))
    for kind in KINDS_BY_ARTIFACT[artifact]:
        spec = ROWS[kind]
        rows = doc.get(spec["list"]) or []
        for i, row in enumerate(rows):
            label = "%s %s[%d]" % (name, spec["list"], i)
            _check_fields(row, spec["fields"], label, problems)
            for (k, field), sub in NESTED.items():
                if k == kind and isinstance(row.get(field), dict):
                    _check_fields(row[field], sub, "%s.%s" % (label, field), problems)
        keys = [_natural(r.get(spec["sort"])) for r in rows]
        if keys != sorted(keys):
            problems.append("%s: %s not sorted by %s" % (name, spec["list"], spec["sort"]))
    return problems
