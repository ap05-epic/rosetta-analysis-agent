"""Investigation tools the LLM calls over a ParsedLog.

Token discipline lives here: tools return condensed, capped summaries and
short excerpts — the full raw log is never sent to the model.
"""

import re
from collections import defaultdict

from .contracts import ParsedLog

_MAX_GROUPS = 10
_MAX_SAMPLES = 5
_MAX_SEARCH_RESULTS = 20
_MAX_LINE_CHARS = 300

_ERROR_LEVELS = ("ERROR", "CRITICAL")
_WARN_LEVELS = ("WARNING",)


def _trim(text: str) -> str:
    return text if len(text) <= _MAX_LINE_CHARS else text[:_MAX_LINE_CHARS] + "…"


def _signature(message: str) -> str:
    """Collapse variable parts so similar messages group together."""
    sig = re.sub(r"0x[0-9a-fA-F]+", "<hex>", message)
    sig = re.sub(r"\d+(?:\.\d+)*", "<n>", sig)  # no \b: must catch 30001ms, txn=88141
    sig = re.sub(r'"[^"]*"', '"<str>"', sig)
    return sig.strip()[:160]


class LogTools:
    """The four tools, bound to one parsed log."""

    def __init__(self, parsed: ParsedLog):
        self.parsed = parsed
        self._by_line = {e.line_number: e for e in parsed.entries}

    # ------------------------------------------------------------ tool 1
    def get_error_summary(self) -> dict:
        """Error/warning groups with counts, sources, first/last seen, sample lines."""
        groups: dict = {}
        for e in self.parsed.entries:
            if e.level not in _ERROR_LEVELS + _WARN_LEVELS:
                continue
            key = (e.level, _signature(e.message))
            g = groups.setdefault(key, {
                "level": e.level, "message_signature": key[1],
                "sample_message": _trim(e.message), "count": 0,
                "sources": set(), "first_seen": e.time, "last_seen": e.time,
                "sample_line_numbers": [],
            })
            g["count"] += 1
            if e.source:
                g["sources"].add(e.source)
            g["last_seen"] = e.time or g["last_seen"]
            if g["first_seen"] is None:
                g["first_seen"] = e.time
            if len(g["sample_line_numbers"]) < _MAX_SAMPLES:
                g["sample_line_numbers"].append(e.line_number)

        ordered = sorted(groups.values(),
                         key=lambda g: (g["level"] not in _ERROR_LEVELS, -g["count"]))
        for g in ordered:
            g["sources"] = sorted(g["sources"])
        return {
            "total_error_lines": sum(1 for e in self.parsed.entries if e.level in _ERROR_LEVELS),
            "total_warning_lines": sum(1 for e in self.parsed.entries if e.level in _WARN_LEVELS),
            "total_lines": len(self.parsed.entries),
            "groups": ordered[:_MAX_GROUPS],
            "groups_truncated": max(0, len(ordered) - _MAX_GROUPS),
        }

    # ------------------------------------------------------------ tool 2
    def get_context_window(self, line_number: int, n: int = 5) -> dict:
        """The n lines before and after a given line."""
        n = max(1, min(int(n), 15))
        line_number = int(line_number)
        lines = [
            {"line_number": e.line_number, "level": e.level,
             "time": e.time, "source": e.source, "raw": _trim(e.raw)}
            for e in self.parsed.entries
            if line_number - n <= e.line_number <= line_number + n
        ]
        return {"center": line_number, "lines": lines,
                "note": None if lines else f"line {line_number} not found in input"}

    # ------------------------------------------------------------ tool 3
    def get_source_stats(self) -> dict:
        """Volume and error rate per source, with active time range."""
        stats: dict = defaultdict(lambda: {"total": 0, "errors": 0, "warnings": 0,
                                           "first_seen": None, "last_seen": None})
        for e in self.parsed.entries:
            s = stats[e.source or "(unattributed)"]
            s["total"] += 1
            s["errors"] += e.level in _ERROR_LEVELS
            s["warnings"] += e.level in _WARN_LEVELS
            if e.time:
                s["first_seen"] = s["first_seen"] or e.time
                s["last_seen"] = e.time
        out = []
        for name, s in stats.items():
            out.append({"source": name, **s,
                        "error_rate": round(s["errors"] / s["total"], 3)})
        out.sort(key=lambda s: (-s["errors"], -s["total"]))
        return {"sources": out[:15], "sources_truncated": max(0, len(out) - 15)}

    # ------------------------------------------------------------ tool 4
    def search_logs(self, pattern: str, max_results: int = _MAX_SEARCH_RESULTS) -> dict:
        """Targeted regex lookup over raw lines (case-insensitive)."""
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return {"error": f"invalid regex: {exc}", "matches": []}
        max_results = max(1, min(int(max_results), _MAX_SEARCH_RESULTS))
        matches, total = [], 0
        for e in self.parsed.entries:
            if rx.search(e.raw):
                total += 1
                if len(matches) < max_results:
                    matches.append({"line_number": e.line_number, "level": e.level,
                                    "time": e.time, "source": e.source, "raw": _trim(e.raw)})
        return {"pattern": pattern, "total_matches": total, "matches": matches}

    # -------------------------------------------------- dispatch for the loop
    def dispatch(self, name: str, arguments: dict) -> dict:
        fn = {
            "get_error_summary": self.get_error_summary,
            "get_context_window": self.get_context_window,
            "get_source_stats": self.get_source_stats,
            "search_logs": self.search_logs,
        }.get(name)
        if fn is None:
            return {"error": f"unknown tool: {name}"}
        try:
            return fn(**arguments)
        except TypeError as exc:
            return {"error": f"bad arguments for {name}: {exc}"}


# OpenAI-format tool schemas the loop advertises to the model.
TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_error_summary",
        "description": "Grouped error/warning summary: counts, sources, first/last seen, sample line numbers. Call this first.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_context_window",
        "description": "Return the lines surrounding a given line number, to see what happened before/after an error.",
        "parameters": {"type": "object", "properties": {
            "line_number": {"type": "integer", "description": "Center line"},
            "n": {"type": "integer", "description": "Lines of context each side (default 5, max 15)"}},
            "required": ["line_number"]}}},
    {"type": "function", "function": {
        "name": "get_source_stats",
        "description": "Per-source volume, error/warning counts, error rate, and active time range.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "search_logs",
        "description": "Case-insensitive regex search over raw log lines. Use to verify a hypothesis.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Regex pattern"},
            "max_results": {"type": "integer", "description": "Cap on returned matches (default 20)"}},
            "required": ["pattern"]}}},
]
