"""Assert every generated log classifies the way its filename claims.

Replicates classifier/regex.py exactly (PASS/FAIL markers, CATEGORY_PATTERNS
order, last-marker-wins). The classifier scans the WHOLE file and returns the
FIRST category whose pattern matches, so a stray word like "timeout" in an
unrelated line silently changes a log's category. This catches that.

Run:  python3 sample-logs/verify_category_logs.py
Exit code 0 = every log classifies as intended.
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent

PASS_PATTERNS = [r"Marking task as SUCCESS", r"Task exited with return code 0"]
FAIL_PATTERNS = [r"Marking task as FAILED", r"Task failed with exception",
                 r"Task exited with return code [1-9]\d*"]

CATEGORY_PATTERNS = [
    ("SQL_SCHEMA_ERROR", [r"relation \"[^\"]+\" does not exist",
                          r"column [a-z0-9_.]+ does not exist",
                          r"UndefinedTable", r"UndefinedColumn"]),
    ("SQL_SYNTAX_ERROR", [r"syntax error at or near", r"psycopg2\.errors\.SyntaxError"]),
    ("SQL_TYPE_MISMATCH", [r"operator does not exist:", r"cannot be matched",
                           r"is of type [a-z]+ but expression is of type [a-z]+",
                           r"psycopg2\.errors\.UndefinedFunction"]),
    ("DB_RESOURCE_EXHAUSTION", [r"high VMem usage", r"out of memory", r"OOM", r"memory limit"]),
    ("DB_CONNECTION_ERROR", [r"connection to server .* failed",
                             r"remaining connection slots are reserved",
                             r"could not connect", r"connection reset",
                             r"broken pipe", r"OperationalError"]),
    ("PERMISSION_ERROR", [r"permission denied", r"InsufficientPrivilege",
                          r"forbidden", r"unauthorized"]),
    ("MODULE_IMPORT_ERROR", [r"No module named", r"ImportError", r"ModuleNotFoundError"]),
    ("TIMEOUT", [r"timed out", r"timeout", r"execution timeout", r"deadline exceeded"]),
    ("RETURN_CODE_FAILURE", [r"Task exited with return code [1-9]\d*", r"exit code [1-9]\d*"]),
]

EXPECTED = {
    "cat-01-sql-schema-error.log": ("FAIL", "SQL_SCHEMA_ERROR"),
    "cat-02-sql-syntax-error.log": ("FAIL", "SQL_SYNTAX_ERROR"),
    "cat-03-sql-type-mismatch.log": ("FAIL", "SQL_TYPE_MISMATCH"),
    "cat-04-db-resource-exhaustion.log": ("FAIL", "DB_RESOURCE_EXHAUSTION"),
    "cat-05-db-connection-error.log": ("FAIL", "DB_CONNECTION_ERROR"),
    "cat-06-permission-error.log": ("FAIL", "PERMISSION_ERROR"),
    "cat-07-module-import-error.log": ("FAIL", "MODULE_IMPORT_ERROR"),
    "cat-08-timeout.log": ("FAIL", "TIMEOUT"),
    "cat-09-return-code-failure.log": ("FAIL", "RETURN_CODE_FAILURE"),
    "cat-10-failure-generic.log": ("FAIL", "FAILURE_GENERIC"),
    "cat-11-unknown-format.log": ("FAIL", "UNKNOWN"),
    "cat-12-healthy-pass.log": ("PASS", "PASS"),
}


def _last(text, patterns):
    pos = -1
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            pos = max(pos, m.start())
    return pos


def _category(text):
    for name, patterns in CATEGORY_PATTERNS:
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                return name
    if any(re.search(p, text, re.IGNORECASE) for p in FAIL_PATTERNS):
        return "FAILURE_GENERIC"
    return "UNKNOWN"


def classify(text):
    """Mirror of classifier.regex.classify_log."""
    fail_pos, pass_pos = _last(text, FAIL_PATTERNS), _last(text, PASS_PATTERNS)
    if fail_pos >= 0 and pass_pos >= 0:
        return ("FAIL", _category(text)) if fail_pos > pass_pos else ("PASS", "PASS")
    if fail_pos >= 0:
        return "FAIL", _category(text)
    if pass_pos >= 0:
        return "PASS", "PASS"
    inferred = _category(text)
    if inferred not in {"UNKNOWN", "PASS"}:
        return "FAIL", inferred
    return "FAIL", "UNKNOWN"


def main():
    failures = 0
    print(f"{'file':38s} {'lines':>6s}  {'expected':26s} {'actual':26s} ok")
    print("-" * 108)
    for name, (want_status, want_cat) in EXPECTED.items():
        path = HERE / name
        if not path.exists():
            print(f"{name:38s} {'--':>6s}  {want_status+'/'+want_cat:26s} {'FILE MISSING':26s} NO")
            failures += 1
            continue
        text = path.read_text(encoding="utf-8")
        status, cat = classify(text)
        ok = (status, cat) == (want_status, want_cat)
        failures += not ok
        print(f"{name:38s} {text.count(chr(10)):6d}  {want_status+'/'+want_cat:26s} "
              f"{status+'/'+cat:26s} {'yes' if ok else 'NO'}")
    print("-" * 108)
    if failures:
        print(f"{failures} log(s) do not classify as intended.")
        print("Fix: find the earlier-category word that leaked in — the classifier "
              "returns the FIRST match in CATEGORY_PATTERNS order, scanning the whole file.")
        return 1
    print("All logs classify as intended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
