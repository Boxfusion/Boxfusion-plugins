"""The workbook's Developer Comments column: placed on every sheet, read back, carried forward.

Runs two ways, with no third-party dependency:
    python tests/test_workbook_comments.py      # prints OK / raises AssertionError
    pytest tests/test_workbook_comments.py      # discovered as test_* functions
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.dirname(HERE)
sys.path.insert(0, RESOURCES)

import export_workbook as wb  # noqa: E402


def sample_sheets():
    sheets = {name: [] for name in wb.SHEETS}
    sheets["Endpoints"] = [
        {"Module": "Shesha", "path": "/api/StoredFile/Download", "Source File": "x.json"},
        {"Module": "Shesha", "path": "/api/StoredFile", "Source File": "x.json"},
    ]
    sheets["Findings"] = [
        # a registered check is keyed by checkId@anchor, a probe row by its title
        {"Module": "app", "id": "WEB-7", "checkId": "A11", "anchor": "Startup.cs",
         "title": "Elmah", "Source File": "y.json"},
        {"Module": "_probe-findings", "id": "ANO-1", "title": "GET /elmah -> OPEN as anonymous",
         "Source File": "z.json"},
    ]
    sheets["Roles"] = [{"Module": "_unattributed", "role": "Branch Manager", "Source File": "r.json"}]
    return sheets


def write(sheets):
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    with open(path, "wb") as fh:
        fh.write(wb.build_xlsx(sheets))
    return path


def test_column_on_every_sheet():
    for sheet in wb.SHEETS:
        cols = wb.columns_for(sheet, [])
        assert wb.COMMENTS in cols, sheet
        # straight after the leading columns, before the rest of the schema
        assert cols.index(wb.COMMENTS) == len(wb.LEAD[sheet]), sheet


def test_round_trip_and_carry_forward():
    first = sample_sheets()
    first["Endpoints"][0][wb.COMMENTS] = "Raised with framework team"
    first["Findings"][0][wb.COMMENTS] = "Fixed in PR 456"
    first["Findings"][1][wb.COMMENTS] = "Accepted for now"
    path = write(first)
    try:
        comments = wb.read_comments(path)
    finally:
        os.remove(path)
    assert comments == {
        ("Endpoints", "Shesha", "/api/StoredFile/Download"): "Raised with framework team",
        ("Findings", "app", "A11@Startup.cs"): "Fixed in PR 456",
        ("Findings", "_probe-findings", "GET /elmah -> OPEN as anonymous"): "Accepted for now",
    }, comments

    # a later run renumbers the run-local id; the comment still follows the finding
    second = sample_sheets()
    second["Findings"][1]["id"] = "ANO-9"
    left = wb.apply_comments(second, comments)
    assert left == {}
    assert second["Findings"][1][wb.COMMENTS] == "Accepted for now"
    assert second["Endpoints"][0][wb.COMMENTS] == "Raised with framework team"
    assert wb.COMMENTS not in second["Endpoints"][1]


def test_orphaned_comment_is_returned():
    sheets = sample_sheets()
    left = wb.apply_comments(sheets, {("Roles", "_unattributed", "Gone Role"): "retire"})
    assert left == {("Roles", "_unattributed", "Gone Role"): "retire"}


def test_unchanged_catalogue_is_byte_identical_with_comments():
    a, b = sample_sheets(), sample_sheets()
    a["Roles"][0][wb.COMMENTS] = b["Roles"][0][wb.COMMENTS] = "Retire"
    assert wb.build_xlsx(a) == wb.build_xlsx(b)


if __name__ == "__main__":
    tests = sorted(n for n in dir() if n.startswith("test_"))
    for name in tests:
        globals()[name]()
        print("  PASS %s" % name)
    print("\n%d workbook comment test(s) passed" % len(tests))
