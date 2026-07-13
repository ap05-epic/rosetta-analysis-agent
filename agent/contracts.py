"""Input/output contracts for the Rosetta agent.

ParsedLog is what the agent consumes (from Reed's parser or the built-in fallback).
AnalysisResult is what the agent produces (what the UI renders).
Everything is plain-JSON friendly: timestamps are ISO strings, no datetimes on the wire.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]
OverallStatus = Literal["critical", "degraded", "healthy", "inconclusive"]

MAX_INCIDENTS = 3


# ---------------------------------------------------------------- input side

class LogEntry(BaseModel):
    """One parsed log line. Only line_number and raw are guaranteed."""

    line_number: int
    raw: str
    time: Optional[str] = None       # ISO-ish string if the parser found one
    source: Optional[str] = None     # file / service / component that emitted the line
    level: str = "INFO"              # normalized: DEBUG/INFO/WARNING/ERROR/CRITICAL
    message: str = ""                # human part of the line, minus time/level/source


class ParsedLog(BaseModel):
    """The agent's input: a list of entries plus where they came from."""

    log_source: str = "unknown"
    entries: list[LogEntry] = Field(default_factory=list)
    # Set when the only thing we have is the classifier's current minimal
    # {"filename": ..., "status": "PASS|FAIL|UNKNOWN"} response (no entries).
    classifier_status: Optional[str] = None


# --------------------------------------------------------------- output side

class Evidence(BaseModel):
    """A concrete log line backing a claim. line_number must exist in the input."""

    line_number: int
    raw_text: str = ""  # filled by the runtime from the actual entry, never by the model
    timestamp: Optional[str] = None
    source: Optional[str] = None
    why_relevant: str


class Incident(BaseModel):
    title: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    human_explanation: str = Field(
        description="2-4 plain-English sentences a non-technical reader can follow."
    )
    possible_solutions: list[str] = Field(min_length=1, max_length=3)
    evidence: list[Evidence] = Field(default_factory=list)
    affected_sources: list[str] = Field(default_factory=list)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


class Stats(BaseModel):
    total_lines: int = 0
    error_lines: int = 0
    warning_lines: int = 0


class AnalysisResult(BaseModel):
    analysis_id: str
    generated_at: str                # ISO timestamp
    log_source: str
    overall_status: OverallStatus
    stats: Stats
    incidents: list[Incident] = Field(default_factory=list, max_length=MAX_INCIDENTS)

    def summary_line(self) -> str:
        return (
            f"{self.overall_status.upper()} — {len(self.incidents)} incident(s), "
            f"{self.stats.error_lines} errors / {self.stats.warning_lines} warnings "
            f"in {self.stats.total_lines} lines"
        )


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def sort_incidents(incidents: list[Incident]) -> list[Incident]:
    return sorted(incidents, key=lambda i: (SEVERITY_ORDER[i.severity], -i.confidence))
