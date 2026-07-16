"""Input adapters: anything in, ParsedLog out.

Three paths, tried in this order by ``to_parsed_log``:
  a) Reed's future structured JSON  — dict with an ``entries`` list
  b) Reed's current /classify reply — dict with ``filename``/``status`` only
  c) raw log text                   — built-in fallback regex parser

Path (c) is the log-agnostic guarantee: every line becomes an entry no matter
the format; worst case it is level=INFO with the whole line as the message.
"""

import re
from typing import Any, Optional

from .contracts import LogEntry, ParsedLog

# Aliases the team has used on the whiteboard vs. what our contract calls them.
_TIME_KEYS = ("time", "timestamp", "ts", "datetime", "date")
_SOURCE_KEYS = ("source", "file", "service", "component", "logger", "origin")
_LEVEL_KEYS = ("level", "status", "severity", "loglevel")
_MESSAGE_KEYS = ("message", "description", "msg", "text", "body")
_RAW_KEYS = ("raw", "raw_line", "line", "original")
_LINE_NO_KEYS = ("line_number", "lineno", "line_no", "n", "index")

_LEVEL_NORMALIZE = {
    "WARN": "WARNING", "ERR": "ERROR", "FATAL": "CRITICAL", "CRIT": "CRITICAL",
    "TRACE": "DEBUG", "NOTICE": "INFO", "FAIL": "ERROR", "SEVERE": "ERROR",
}


def _pick(d: dict, keys: tuple) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def normalize_level(value: Any) -> str:
    lvl = str(value or "INFO").strip().upper()
    return _LEVEL_NORMALIZE.get(lvl, lvl if lvl in
                                ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else "INFO")


# ------------------------------------------------------- (a) structured JSON

def from_structured(data: dict) -> ParsedLog:
    """Reed's future per-entry JSON. Tolerant of field-name variations."""
    entries = []
    for i, item in enumerate(data.get("entries", []), start=1):
        if isinstance(item, str):  # tolerate a plain list of lines
            entries.append(_parse_line(item, i))
            continue
        raw = _pick(item, _RAW_KEYS) or str(_pick(item, _MESSAGE_KEYS) or "")
        entries.append(LogEntry(
            line_number=int(_pick(item, _LINE_NO_KEYS) or i),
            raw=raw,
            time=(str(_pick(item, _TIME_KEYS)) if _pick(item, _TIME_KEYS) is not None else None),
            source=(str(_pick(item, _SOURCE_KEYS)) if _pick(item, _SOURCE_KEYS) is not None else None),
            level=normalize_level(_pick(item, _LEVEL_KEYS)),
            message=str(_pick(item, _MESSAGE_KEYS) or raw),
        ))
    return ParsedLog(
        log_source=str(data.get("log_source") or data.get("filename") or "parsed-json"),
        entries=entries,
    )


# ------------------------------------------- (b) current minimal /classify

def from_classifier_minimal(data: dict) -> ParsedLog:
    """Reed's current {"filename": ..., "status": PASS|FAIL|UNKNOWN}. No lines
    to investigate — core.analyze() reports honestly instead of guessing."""
    return ParsedLog(
        log_source=str(data.get("filename", "classifier")),
        entries=[],
        classifier_status=str(data.get("status", "UNKNOWN")).upper(),
    )


# ------------------------------------------------- (c) fallback raw parser

# timestamp shapes: ISO (2026-07-13T08:01:02.123Z / 2026-07-13 08:01:02,123),
# syslog (Jul 13 08:01:02), bracketed ([13/Jul/2026:08:01:02 +0000]), epoch-ish.
_TS_PATTERNS = [
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2}(?: [+-]\d{4})?"),
    re.compile(r"[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2}"),
    re.compile(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"),
]

_LEVEL_PATTERN = re.compile(
    r"(?:^|[\s\[\(:])(?:level[=:]\s*)?"
    r"(CRITICAL|FATAL|SEVERE|ERROR|ERR|WARNING|WARN|NOTICE|INFO|DEBUG|TRACE)"
    r"(?:[\s\]\):=,]|$)", re.IGNORECASE)

# source: svc=name, [service-name], "LEVEL logger - msg" (log4j), "proc[pid]:" (syslog)
_SOURCE_PATTERNS = [
    re.compile(r"\b(?:service|svc|app|component|logger)[=:]\s*([\w.\-]+)", re.IGNORECASE),
    re.compile(r"\[([a-zA-Z][\w.\-]{1,40})\]"),
    re.compile(r"(?:ERROR|WARN(?:ING)?|INFO|DEBUG|CRITICAL|FATAL)\s+([a-zA-Z][\w.\-]{1,40})\s+-\s"),
    re.compile(r"\]\s+([a-zA-Z][\w.\-]{1,40})\s+-\s"),  # "[ERROR] pipeline.worker - msg"
    re.compile(r"(?:^|\s)([a-z][\w\-]{2,30})(?:\[\d+\])?:\s"),
]

_STATUS_5XX = re.compile(r'(?:"\s*|status[=: ])(5\d{2})\b')
_STATUS_4XX = re.compile(r'(?:"\s*|status[=: ])(4\d{2})\b')
_EXCEPTION = re.compile(r"\b\w+(?:Exception|Error)\b|Traceback \(most recent call last\)")

_NOT_SOURCES = {"error", "warn", "warning", "info", "debug", "critical", "fatal", "trace", "notice"}


def _parse_line(line: str, line_number: int) -> LogEntry:
    time = None
    for pat in _TS_PATTERNS:
        m = pat.search(line)
        if m:
            time = m.group(0)
            break

    level = None
    m = _LEVEL_PATTERN.search(line)
    if m:
        level = normalize_level(m.group(1))
    elif _STATUS_5XX.search(line) or _EXCEPTION.search(line):
        level = "ERROR"
    elif _STATUS_4XX.search(line):
        level = "WARNING"
    else:
        level = "INFO"

    source = None
    for pat in _SOURCE_PATTERNS:
        m = pat.search(line)
        if m and m.group(1).lower() not in _NOT_SOURCES:
            source = m.group(1)
            break

    # message = the line minus timestamp/level prefixes; raw stays lossless
    message = line
    if time and line.find(time) < 8:
        message = line[line.find(time) + len(time):].lstrip(" -:[]")
    message = re.sub(
        r"^(?:CRITICAL|FATAL|SEVERE|ERROR|ERR|WARNING|WARN|NOTICE|INFO|DEBUG|TRACE)"
        r"\]?\s*[-:]?\s+", "", message, flags=re.IGNORECASE)
    return LogEntry(line_number=line_number, raw=line, time=time,
                    source=source, level=level, message=message.strip())


def from_raw_text(text: str, log_source: str = "raw-log") -> ParsedLog:
    entries = [
        _parse_line(line, i)
        for i, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    return ParsedLog(log_source=log_source, entries=entries)


# ------------------------------------------------------------------ router

def to_parsed_log(data: Any, log_source: Optional[str] = None) -> ParsedLog:
    """Accept a dict (parser output), JSON-looking string, or raw log text."""
    if isinstance(data, ParsedLog):
        return data
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    if isinstance(data, dict):
        if isinstance(data.get("entries"), list):
            parsed = from_structured(data)
        elif "filename" in data or "status" in data:
            parsed = from_classifier_minimal(data)
        else:
            raise ValueError(
                "Unrecognized JSON shape: expected {'entries': [...]} or "
                "{'filename': ..., 'status': ...}")
    elif isinstance(data, str):
        stripped = data.strip()
        if stripped.startswith("{"):
            import json
            try:
                return to_parsed_log(json.loads(stripped), log_source)
            except ValueError:
                pass  # JSON-looking but not parser output -> treat as raw text
        parsed = from_raw_text(data, log_source or "raw-log")
    else:
        raise ValueError(f"Cannot adapt input of type {type(data).__name__}")
    if log_source:
        parsed.log_source = log_source
    return parsed
