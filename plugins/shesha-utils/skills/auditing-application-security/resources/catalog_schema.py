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
            # Determinism standard (references/determinism-standard.md §2-§7). These make a
            # finding reproducible run-over-run. All nullable/defaulted, so rows built before
            # the determinism fields were wired keep validating (one release of back-compat).
            # checkId@anchor is the stable finding id; line numbers live only in `locator`.
            ("checkId", "s?", None), ("anchor", "s?", None), ("locator", "s?", None),
            ("evidenceLevel", "s?", None), ("severityScore", "s?", None),
            ("impactClass", "s?", None), ("reachability", "s?", None),
            ("dataSensitivity", "s?", None), ("planId", "s?", None),
            ("rootCause", "s?", None), ("subArea", "s?", None),
            ("nonDeterministic", "b", False),
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


# ============================================================================ determinism
# references/determinism-standard.md + references/check-registry.md.
# This file is the single format source, so the registry, the severity-scoring key, the
# finding-id grammar and the canonical-form helpers all live here; findings.py,
# build_catalogs.py, verify_run.py, normalize_findings.py and diff_runs.py key off them.

# Severity scoring key (determinism-standard §4; the registry's scoring table). Severity is
# DERIVED from three declared inputs, never asserted: base(impact_class, reachability), then
# shifted one band per data_sensitivity. Evidence level is NOT an input.
SEVERITY_BANDS = ["Info", "Low", "Medium", "High", "Critical"]  # ascending

_BASE_SEVERITY = {
    "auth_bypass":       {"anonymous": "Critical", "any_authenticated": "High",
                          "low_priv": "High", "admin_only": "Medium", "local_only": "Low"},
    "data_exposure_pii": {"anonymous": "Critical", "any_authenticated": "High",
                          "low_priv": "High", "admin_only": "Medium", "local_only": "Low"},
    "data_integrity":    {"anonymous": "High", "any_authenticated": "High",
                          "low_priv": "Medium", "admin_only": "Medium", "local_only": "Low"},
    "dos":               {"anonymous": "High", "any_authenticated": "Medium",
                          "low_priv": "Medium", "admin_only": "Low", "local_only": "Low"},
    "info_leak":         {"anonymous": "High", "any_authenticated": "Medium",
                          "low_priv": "Low", "admin_only": "Low", "local_only": "Low"},
    "maintainability":   {"anonymous": "Low", "any_authenticated": "Low", "low_priv": "Low",
                          "admin_only": "Low", "local_only": "Low"},
}
# popia_special raises one band; pii_basic is per-check (held at +0 for a total function here);
# business/none do not shift. Capped at Critical.
_SENS_SHIFT = {"popia_special": 1, "pii_basic": 0, "business": 0, "none": 0}


def severity_score(impact_class, reachability, data_sensitivity):
    """The derived severity band (determinism-standard §4), or None if inputs are unscored."""
    base = _BASE_SEVERITY.get(impact_class, {}).get(reachability)
    if base is None:
        return None
    idx = SEVERITY_BANDS.index(base) + _SENS_SHIFT.get(data_sensitivity or "none", 0)
    idx = max(0, min(idx, len(SEVERITY_BANDS) - 1))
    return SEVERITY_BANDS[idx]


def severity_rank(band):
    """Most-severe-first ordering key for a band name (Critical -> 0)."""
    try:
        return len(SEVERITY_BANDS) - 1 - SEVERITY_BANDS.index(band)
    except (ValueError, TypeError):
        return len(SEVERITY_BANDS)  # unknown bands sort last


# The registry, keyed by the check id each scanner EMITS today (source_scan.py STARTUP_CHECKS
# / SETTINGS_CHECKS, posture_scan.py T/R/G/D group checks). The value carries the registered
# CHECK-ID (with the renames G1->B7 and D1/D2->K1/K2 baked in, registry decision 1), the three
# scored-severity inputs, the root_cause / sub_area / plan_id, and whether the check is DET
# (enters the byte-identity diff) or ND (non_deterministic, dropped from the diff until its
# instrument lands). Sub-area uses determinism-standard §9 vocabulary.
AC, SC, ID, RT = ("access-control", "secrets-and-config", "input-and-data",
                  "real-time-and-messaging")


def _r(check_id, impact, reach, sens, rc, area, nd=False, plan=None):
    return {"checkId": check_id, "impactClass": impact, "reachability": reach,
            "dataSensitivity": sens, "rootCause": rc, "subArea": area,
            "nonDeterministic": nd, "planId": plan or ("PLAN-%s" % check_id.lower())}


CHECK_REGISTRY = {
    # A - web host config (Startup.cs). Guard detection is ND; presence is DET.
    "A1-cors-origins":      _r("A1", "info_leak", "anonymous", "none", "RC-sec-cors", SC),
    "A2-cors-wildcard":     _r("A2", "info_leak", "anonymous", "none", "RC-sec-cors", SC),
    "A3-cors-credentials":  _r("A3", "auth_bypass", "anonymous", "none", "RC-sec-cors", SC),
    "A2+A3":                _r("A3", "auth_bypass", "anonymous", "none", "RC-sec-cors", SC),
    "A4-graphql-playground": _r("A4", "info_leak", "anonymous", "none",
                                "RC-sec-starter-surface", SC),
    "A5-swagger-ui":        _r("A5", "info_leak", "anonymous", "none",
                               "RC-sec-starter-surface", SC),
    "A5-swagger":           _r("A5", "info_leak", "anonymous", "none",
                               "RC-sec-starter-surface", SC),
    "A6-security-headers":  _r("A6", "info_leak", "anonymous", "none", "RC-sec-headers", SC),
    "A7-csp":               _r("A7", "info_leak", "anonymous", "none", "RC-sec-headers", SC),
    "A8-hsts":              _r("A8", "info_leak", "anonymous", "none", "RC-sec-headers", SC),
    "A9-auth-filter":       _r("A9", "auth_bypass", "anonymous", "none",
                               "RC-sec-authz-filter", AC),
    "A10-hangfire":         _r("A10", "auth_bypass", "anonymous", "none",
                               "RC-sec-starter-surface", AC),
    "A11-elmah":            _r("A11", "info_leak", "anonymous", "pii_basic",
                               "RC-sec-starter-surface", AC),
    "A12-env-guard":        _r("A12", "info_leak", "anonymous", "none",
                               "RC-sec-starter-surface", SC),
    # B - appsettings committed secrets & config.
    "B1-jwt-key":           _r("B1", "auth_bypass", "anonymous", "none",
                               "RC-sec-committed-secret", SC),
    "B2-passphrase":        _r("B2", "data_integrity", "any_authenticated", "none",
                               "RC-sec-config", SC),
    "B3-cors-origins":      _r("B3", "info_leak", "anonymous", "none", "RC-sec-cors", SC),
    "B4-conn-password":     _r("B4", "data_exposure_pii", "admin_only", "none",
                               "RC-sec-committed-secret", SC),
    "B5-smtp":              _r("B5", "data_exposure_pii", "admin_only", "none",
                               "RC-sec-committed-secret", SC),
    # B7 (was G1-secrets): secrets in tracked config / git history.
    "G1-secrets-in-tracked-config": _r("B7", "data_exposure_pii", "anonymous", "none",
                                       "RC-sec-committed-secret", SC),
    # C - services / controllers. Hand-routed controller with no class-level auth attribute.
    "C1-C6":                _r("C1", "auth_bypass", "any_authenticated", "pii_basic",
                               "RC-sec-no-authz", AC),
    # D5 - row-level security: no global specification anywhere (solution-wide absence).
    "D5-specifications":    _r("D5", "data_exposure_pii", "any_authenticated", "pii_basic",
                               "RC-sec-no-rowfilter", AC),
    # I - token & session policy. I2 is DET (reads the committed key); I1/I3/I4 depend on a
    # live token, so they are ND.
    "T2-signing-key":       _r("I2", "auth_bypass", "anonymous", "none",
                               "RC-sec-committed-secret", SC),
    "T1-token":             _r("I3", "auth_bypass", "any_authenticated", "none",
                               "RC-sec-token", SC, nd=True),
    "T3-signoff-invalidates": _r("I4", "auth_bypass", "any_authenticated", "none",
                                 "RC-sec-token", SC, nd=True),
    # J - rate limiting & lockout. Current code emits one combined R1 row; mapped to J1.
    "R1-rate-limiting":     _r("J1", "dos", "anonymous", "none", "RC-sec-dos", AC),
    # K - dependency advisories (renamed from the D1/D2 posture ids). ND: time-varying DB.
    "D1-dotnet-vulnerable": _r("K1", "maintainability", "local_only", "none",
                               "RC-sec-deps", SC, nd=True),
    "D2-npm-audit":         _r("K2", "maintainability", "local_only", "none",
                               "RC-sec-deps", SC, nd=True),
}

# Categories whose findings are intrinsically ND (live probe / live state), so even with no
# registered CHECK-ID they are tagged non_deterministic and dropped from the diff.
ND_CATEGORIES = {"anonymous-access", "authenticated-access", "object-level-authorization",
                 "default-credentials"}

# Evidence-level enum (determinism-standard §3), strongest first.
EVIDENCE_LEVELS = ["REPRODUCED", "CONFIRMED-IN-LOGS", "VERIFIED-ARTEFACT", "CODE-ONLY",
                   "DATA-ANOMALY", "NOT-ASSESSED"]

_LINE_SUFFIX = re.compile(r":\d+$")


def norm_path(path):
    """Repo-root-relative path -> `/` separators -> lowercased, with any `:line` stripped.
    The path part of an anchor only; a `#Symbol.Member` is kept verbatim by the caller."""
    if not path:
        return ""
    p = str(path).replace("\\", "/")
    p = _LINE_SUFFIX.sub("", p)
    return p.lower()


def anchor_member(path, symbol):
    """C# member / type anchor: `<path>#<Type>.<Member>` (determinism-standard §2)."""
    return "%s#%s" % (norm_path(path), symbol)


def anchor_key(path, section_key):
    """Config-key anchor: `<path>#key:<Section>:<Key>`."""
    return "%s#key:%s" % (norm_path(path), section_key)


def finding_id(check_id, anchor):
    """The stable finding id: `<CHECK-ID>@<anchor>` (determinism-standard §2)."""
    return "%s@%s" % (check_id, anchor)


def finding_meta(origin, anchor, evidence_level=None, locator=None, category=None):
    """The determinism field block for one finding row, from its emitting check id.

    `origin` is the scanner's own check id (e.g. `A9-auth-filter`, `G1-secrets-in-tracked-
    config`, `D1-dotnet-vulnerable`). An unregistered origin, or one in an ND category, is
    tagged non_deterministic with no CHECK-ID, so the normalizer drops it from the diff.
    """
    entry = CHECK_REGISTRY.get(origin)
    if entry is None or (category in ND_CATEGORIES):
        return {
            "checkId": entry["checkId"] if entry else None,
            "anchor": anchor, "locator": locator,
            "evidenceLevel": evidence_level or "NOT-ASSESSED",
            "severityScore": None, "impactClass": None, "reachability": None,
            "dataSensitivity": None, "planId": entry["planId"] if entry else None,
            "rootCause": entry["rootCause"] if entry else None,
            "subArea": entry["subArea"] if entry else None,
            "nonDeterministic": True,
        }
    return {
        "checkId": entry["checkId"], "anchor": anchor, "locator": locator,
        "evidenceLevel": evidence_level or "CODE-ONLY",
        "severityScore": severity_score(entry["impactClass"], entry["reachability"],
                                        entry["dataSensitivity"]),
        "impactClass": entry["impactClass"], "reachability": entry["reachability"],
        "dataSensitivity": entry["dataSensitivity"], "planId": entry["planId"],
        "rootCause": entry["rootCause"], "subArea": entry["subArea"],
        "nonDeterministic": entry["nonDeterministic"],
    }


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
