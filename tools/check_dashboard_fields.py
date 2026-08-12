#!/usr/bin/env python3
"""Guard: keep DASHBOARD_JOB_FIELDS in sync with what the dashboard actually reads.

jobs.json is trimmed to only the job columns dashboard/index.html uses, because
the file is downloaded in full on every page load. That trim is only safe while
the allowlist and the dashboard agree. If someone adds a `j["Equipment Costs"]`
to index.html without adding it to DASHBOARD_JOB_FIELDS, the field would export
as absent and that view would silently render zeros -- no error anywhere.

This script parses index.html for every job-field read and fails if any of them
is missing from the allowlist. CI runs it before each export, so the failure
shows up as a red workflow instead of a wrong dashboard.

Run manually:
    python tools/check_dashboard_fields.py

Exit codes: 0 = in sync, 1 = drift detected.
"""

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = os.path.join(REPO_ROOT, "dashboard", "index.html")

# index.html builds synthetic jobs for its offline demo mode. Those object
# literals mention columns nothing ever reads back, so scanning them would
# demand fields into the allowlist for no reason. Everything from the mock
# generator's start to the MOCK_MEM constant is excluded from the scan.
MOCK_START = re.compile(r"function\s+\w*[Mm]ock\w*\s*\(|function\s+\w*[Dd]emo\w*\s*\(")
MOCK_END = re.compile(r"const\s+MOCK_MEM")


def strip_mock_section(html):
    """Return index.html with the mock-data generator removed."""
    start = MOCK_START.search(html)
    end = MOCK_END.search(html)
    if not start or not end or end.start() <= start.start():
        # Layout changed. Scanning everything is the safe direction: it can only
        # demand extra fields, never miss a real one.
        print("  note: mock-data section not found; scanning the whole file.")
        return html
    return html[: start.start()] + html[end.start() :]


def find_job_field_reads(html):
    """Every job column index.html reads, as a set of field names."""
    body = strip_mock_section(html)
    fields = set()

    # Direct reads: j["Field"] / job['Field'] on a job object.
    for m in re.finditer(r"""\b(?:j|job|jb)\[(["'])(.+?)\1\]""", body):
        fields.add(m.group(2))

    # Grouping keys: groupBy(jobs, 'Field')
    for m in re.finditer(r"""groupBy\s*\(\s*\w+\s*,\s*(["'])(.+?)\1\s*\)""", body):
        fields.add(m.group(2))

    return fields


def load_allowlist():
    """Read the two field lists out of export_to_json.py *without importing it*.

    export_to_json reads os.environ["GOOGLE_SHEET_ID"] at import time, so
    importing it here would make this check depend on the Google/ServiceTitan
    secrets. It runs in CI before those are needed, and should stay runnable by
    anyone who just cloned the repo. Parsing the AST keeps it credential-free.
    """
    import ast

    src_path = os.path.join(REPO_ROOT, "export_to_json.py")
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=src_path)

    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in (
                "DASHBOARD_JOB_FIELDS",
                "JOB_COLUMNS",
            ):
                found[target.id] = ast.literal_eval(node.value)

    for name in ("DASHBOARD_JOB_FIELDS", "JOB_COLUMNS"):
        if name not in found:
            raise SystemExit(
                f"ERROR: could not find {name} as a module-level list in "
                f"{src_path}. If it was renamed or moved inside a function, "
                "update this check to match."
            )

    return list(found["DASHBOARD_JOB_FIELDS"]), list(found["JOB_COLUMNS"])


def main():
    if not os.path.exists(INDEX_HTML):
        print(f"ERROR: {INDEX_HTML} not found.")
        return 1

    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()

    allowlist, job_columns = load_allowlist()
    read = find_job_field_reads(html)

    # Only care about names that are real job columns; membership reads (r["Status"])
    # and other object accesses are out of scope.
    read_job_fields = {f for f in read if f in job_columns}

    missing = sorted(read_job_fields - set(allowlist))
    unused = sorted(set(allowlist) - read_job_fields)

    print(f"Dashboard reads {len(read_job_fields)} job field(s).")
    print(f"Allowlist exports {len(allowlist)} of {len(job_columns)} columns.")

    if missing:
        print()
        print("ERROR: dashboard/index.html reads job fields that the export drops:")
        for f in missing:
            print(f"    - {f!r}")
        print()
        print("  jobs.json would not contain these, so those views would render")
        print("  blanks or zeros. Add them to DASHBOARD_JOB_FIELDS in")
        print("  export_to_json.py (and keep the comment there accurate).")
        return 1

    if unused:
        # Not fatal: exporting a field nothing reads only wastes a little space,
        # and a field may be staged ahead of the UI change that consumes it.
        print()
        print("Note: exported but not read by the dashboard (safe to remove):")
        for f in unused:
            print(f"    - {f!r}")

    print()
    print("OK: every job field the dashboard reads is exported.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
