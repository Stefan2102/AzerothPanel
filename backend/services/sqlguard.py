"""First line of defence for the SQL runner: allow a single read-only statement.

The second (authoritative) line is the READ ONLY transaction in db.run_readonly,
where MySQL itself rejects any write.
"""
import re

ALLOWED = {"select", "show", "describe", "desc", "explain", "with"}
_COMMENTS = re.compile(r"/\*.*?\*/|--[^\n]*|#[^\n]*", re.S)
_STRINGS = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"|`(?:[^`]|``)*`", re.S)
_FORBIDDEN = re.compile(r"\b(into\s+(outfile|dumpfile)|for\s+update|lock\s+in\s+share\s+mode|sleep\s*\(|benchmark\s*\()", re.I)


class QueryRejected(ValueError):
    pass


def check_readonly(sql: str) -> str:
    """Return the statement without a trailing semicolon, or raise QueryRejected."""
    body = _COMMENTS.sub(" ", sql).strip()
    masked = _STRINGS.sub("''", body)
    masked = masked.rstrip().rstrip(";").rstrip()
    if not masked:
        raise QueryRejected("The query is empty.")
    if ";" in masked:
        raise QueryRejected("Only one statement at a time is allowed.")
    first = masked.split(None, 1)[0].lower()
    if first not in ALLOWED:
        raise QueryRejected(f"Only read-only statements are allowed ({', '.join(sorted(ALLOWED)).upper()}).")
    if _FORBIDDEN.search(masked):
        raise QueryRejected("That clause is not allowed in the read-only runner.")
    return body.rstrip().rstrip(";")
