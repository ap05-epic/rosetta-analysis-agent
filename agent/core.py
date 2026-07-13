"""The agentic loop: investigate via tools, emit a validated AnalysisResult.

Hand-rolled on purpose (no LangChain): send messages -> if the model asks for
tools, run them and loop -> if it answers, validate. Hard caps everywhere:
8 iterations, 1 validation retry, and a graceful inconclusive result when the
LLM is unreachable. Trust boundary: everything the model returns is checked —
stats are computed from the data, evidence line numbers are cross-checked
against the input, and fabricated citations are dropped.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError

from .contracts import (MAX_INCIDENTS, AnalysisResult, Evidence, Incident,
                        ParsedLog, Stats, sort_incidents)
from .providers import LLMProvider, ProviderError, get_provider
from .skill_loader import build_system_prompt
from .tools import TOOL_SCHEMAS, LogTools

MAX_ITERATIONS = 8

_ERROR_LEVELS = ("ERROR", "CRITICAL")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _compute_stats(parsed: ParsedLog) -> Stats:
    return Stats(
        total_lines=len(parsed.entries),
        error_lines=sum(1 for e in parsed.entries if e.level in _ERROR_LEVELS),
        warning_lines=sum(1 for e in parsed.entries if e.level == "WARNING"),
    )


def _base_result(parsed: ParsedLog, status: str, incidents: list) -> AnalysisResult:
    return AnalysisResult(
        analysis_id=str(uuid.uuid4()),
        generated_at=_now_iso(),
        log_source=parsed.log_source,
        overall_status=status,
        stats=_compute_stats(parsed),
        incidents=incidents,
    )


def _inconclusive(parsed: ParsedLog, reason: str, solutions: list) -> AnalysisResult:
    return _base_result(parsed, "inconclusive", [Incident(
        title="Analysis could not be completed",
        severity="low",
        confidence=0.0,
        human_explanation=reason,
        possible_solutions=solutions[:3],
        evidence=[],
        affected_sources=[],
    )])


def _classifier_only_result(parsed: ParsedLog) -> AnalysisResult:
    """We only have PASS/FAIL/UNKNOWN from the classifier — report honestly."""
    verdict = parsed.classifier_status or "UNKNOWN"
    if verdict == "PASS":
        return _base_result(parsed, "healthy", [])
    status = "degraded" if verdict == "FAIL" else "inconclusive"
    return _base_result(parsed, status, [Incident(
        title=f"Classifier flagged this log as {verdict}",
        severity="medium" if verdict == "FAIL" else "low",
        confidence=0.3,
        human_explanation=(
            f"The upstream classifier marked '{parsed.log_source}' as {verdict}, "
            "but no per-line log entries were provided, so the root cause cannot "
            "be determined from this input alone. Re-submit the raw log file (or "
            "the parser's per-entry JSON) to get a full analysis with evidence."),
        possible_solutions=[
            "Re-run the analysis with the raw log file so the agent can inspect individual lines.",
            "Upgrade the parser call to return per-entry JSON (time, file, status, description).",
        ],
        evidence=[],
        affected_sources=[],
    )])


# ------------------------------------------------------------ answer parsing

def _extract_json(text: str) -> dict:
    """The model should return bare JSON; tolerate code fences anyway."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    return json.loads(text[start:end + 1])


def _verify_evidence(incidents: list, parsed: ParsedLog) -> None:
    """Anti-hallucination: keep only evidence whose line_number exists in the
    input, and fill raw_text/timestamp/source from the ACTUAL entry (never
    trust the model's transcription). Incidents that lose all evidence keep
    their text but get their confidence knocked down."""
    by_line = {e.line_number: e for e in parsed.entries}
    for inc in incidents:
        verified = []
        for ev in inc.evidence:
            entry = by_line.get(ev.line_number)
            if entry is None:
                continue  # fabricated or stale citation — drop it
            verified.append(Evidence(
                line_number=entry.line_number,
                raw_text=entry.raw,
                timestamp=entry.time,
                source=entry.source,
                why_relevant=ev.why_relevant,
            ))
        if inc.evidence and not verified:
            inc.confidence = min(inc.confidence, 0.3)
            inc.human_explanation += (
                " (Note: the cited log lines could not be verified against the "
                "input, so treat this finding with caution.)")
        inc.evidence = verified


def _finalize(payload: dict, parsed: ParsedLog) -> AnalysisResult:
    """Merge the model's answer with runtime-owned fields and validate."""
    incidents = [Incident.model_validate(i) for i in payload.get("incidents", [])]
    _verify_evidence(incidents, parsed)
    incidents = sort_incidents(incidents)[:MAX_INCIDENTS]
    status = payload.get("overall_status", "inconclusive")
    return _base_result(parsed, status, incidents)


# -------------------------------------------------------------------- driver

def analyze(parsed: ParsedLog, provider: Optional[LLMProvider] = None,
            max_iterations: int = MAX_ITERATIONS) -> AnalysisResult:
    provider = provider or get_provider()

    if not parsed.entries:
        if parsed.classifier_status:
            return _classifier_only_result(parsed)
        return _inconclusive(
            parsed, "The input contained no log entries, so there is nothing to analyze.",
            ["Check that the log file is not empty and was uploaded correctly."])

    tools = LogTools(parsed)
    stats = _compute_stats(parsed)
    messages = [
        {"role": "system", "content": build_system_prompt()},
        # token discipline: the model gets an overview, never the raw log
        {"role": "user", "content": (
            f"Analyze the log '{parsed.log_source}': {stats.total_lines} entries, "
            f"{stats.error_lines} error-level and {stats.warning_lines} warning-level lines, "
            f"spanning line numbers {parsed.entries[0].line_number}-{parsed.entries[-1].line_number}. "
            "Investigate with the tools, then emit the final JSON report.")},
    ]

    retried_validation = False
    try:
        for _ in range(max_iterations):
            reply = provider.chat(messages, TOOL_SCHEMAS)

            if reply.get("tool_calls"):
                messages.append({"role": "assistant", "content": reply.get("content"),
                                 "tool_calls": [
                                     {"id": tc["id"], "type": "function",
                                      "function": {"name": tc["name"],
                                                   "arguments": tc["arguments"]}}
                                     for tc in reply["tool_calls"]]})
                for tc in reply["tool_calls"]:
                    try:
                        args = json.loads(tc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = tools.dispatch(tc["name"], args)
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "name": tc["name"],
                                     "content": json.dumps(result, default=str)})
                continue

            # no tool calls -> this is the final answer
            content = reply.get("content") or ""
            try:
                return _finalize(_extract_json(content), parsed)
            except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                if retried_validation:
                    return _inconclusive(
                        parsed,
                        "The analysis engine produced a malformed report twice, so no "
                        "conclusion is available for this run.",
                        ["Re-run the analysis.",
                         "If this repeats, check the model deployment configuration."])
                retried_validation = True
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": (
                    "Your answer failed schema validation: "
                    f"{exc}. Re-send ONLY the corrected JSON object; keep your "
                    "conclusions unchanged.")})

        return _inconclusive(
            parsed,
            f"The investigation exceeded the {max_iterations}-step budget without "
            "reaching a conclusion, so no reliable root cause can be reported.",
            ["Re-run the analysis.",
             "If this repeats, the log may be too ambiguous — try a narrower time window."])
    except ProviderError as exc:
        return _inconclusive(
            parsed,
            "The analysis engine (LLM) could not be reached, so the log was not "
            f"investigated. Technical detail: {exc}",
            ["Check the Azure OpenAI environment variables and network access.",
             "Run with --mock (or ROSETTA_PROVIDER=mock) to test the pipeline without an LLM."])


def analyze_input(data, provider: Optional[LLMProvider] = None,
                  log_source: Optional[str] = None) -> AnalysisResult:
    """Convenience: adapt any supported input shape, then analyze."""
    from .adapters import to_parsed_log
    return analyze(to_parsed_log(data, log_source), provider)
