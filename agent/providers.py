"""LLM provider layer: one tiny interface, two implementations.

AzureOpenAIProvider — real calls, configured entirely by env vars.
MockProvider        — deterministic, zero-network. It runs a scripted
investigation through the SAME tool loop (summary -> source stats -> context)
and then writes its final answer FROM the actual tool results, so `--mock`
produces a real, evidence-cited report for any input log, not just the samples.

Both return OpenAI chat-completions-shaped dicts:
  {"content": str|None, "tool_calls": [{"id","name","arguments"}] | None}
"""

import json
import os
from typing import Optional

TEMPERATURE = 0.1  # low temperature everywhere: we want repeatable analysis


class ProviderError(RuntimeError):
    """LLM unreachable/misconfigured. core.analyze turns this into an
    inconclusive result instead of crashing."""


class LLMProvider:
    name = "base"

    def chat(self, messages: list, tools: list) -> dict:
        raise NotImplementedError


# --------------------------------------------------------------------- azure

class AzureOpenAIProvider(LLMProvider):
    name = "azure"

    def __init__(self):
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
        if not (endpoint and api_key and self.deployment):
            raise ProviderError(
                "Azure OpenAI not configured: set AZURE_OPENAI_ENDPOINT, "
                "AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT "
                "(and optionally AZURE_OPENAI_API_VERSION), or run with --mock.")
        try:
            from openai import AzureOpenAI
        except ImportError as exc:
            raise ProviderError(f"openai package not installed: {exc}")
        self._client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key,
                                   api_version=api_version)

    def chat(self, messages: list, tools: list) -> dict:
        try:
            resp = self._client.chat.completions.create(
                model=self.deployment, messages=messages, tools=tools,
                temperature=TEMPERATURE)
        except Exception as exc:  # network/auth/quota: all become inconclusive
            raise ProviderError(f"Azure OpenAI call failed: {exc}")
        msg = resp.choices[0].message
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [{"id": tc.id, "name": tc.function.name,
                           "arguments": tc.function.arguments} for tc in msg.tool_calls]
        return {"content": msg.content, "tool_calls": tool_calls}


# ---------------------------------------------------------------------- mock

# keyword -> (title hint, solutions) knowledge base for the canned analyst.
# Order matters: first match wins, so specific phrases go before broad ones.
_PLAYBOOK = [
    (("connection refused", "connection reset", "unreachable", "no route to host"),
     "Dependency unreachable", [
        "Check whether the named dependency (host/port in the cited lines) is up and accepting connections.",
        "Verify network path and DNS between the caller and the dependency.",
        "Fail over to a replica or restart the dependency if it is down.",
    ]),
    (("pool", "hikari"), "Database connection pool exhaustion", [
        "Increase the database connection pool size (or lower per-request hold time) and restart the affected service.",
        "Check the database server for slow queries or locks that are holding connections open.",
        "Add a circuit breaker / timeout so dependent services fail fast instead of queueing.",
    ]),
    (("timeout", "timed out"), "Downstream timeouts", [
        "Identify the slow dependency and confirm it is healthy before restarting callers.",
        "Raise or tune the client timeout only after the root bottleneck is fixed.",
    ]),
    (("deploy", "release", "version", "rollout"), "Faulty deployment", [
        "Roll back to the previous release immediately.",
        "Reproduce the failing request locally against the new build before re-deploying.",
        "Add the failing case to the pre-deploy smoke test suite.",
    ]),
    (("nullpointer", "exception", "traceback", "500", "502", "503", "504"),
     "Application errors (HTTP 5xx)", [
        "Inspect the stack trace at the cited lines and fix the failing code path.",
        "Roll back if the errors began right after a deployment.",
    ]),
    (("memory", "oom", "heap"), "Memory exhaustion", [
        "Restart the affected service to recover, then review memory limits.",
        "Capture a heap profile to find the leak before raising limits.",
    ]),
    (("disk", "space", "no space"), "Disk space exhaustion", [
        "Free disk space (rotate/compress logs) on the affected host.",
        "Add disk usage alerting well below 100%.",
    ]),
]

_DEFAULT_SOLUTIONS = [
    "Investigate the cited log lines with the owning team.",
    "Check recent changes (deploys, config, infrastructure) around the first occurrence time.",
]


def _playbook_lookup(text: str):
    low = text.lower()
    for keywords, title, solutions in _PLAYBOOK:
        if any(k in low for k in keywords):
            return title, solutions[:3]
    return None, _DEFAULT_SOLUTIONS


class MockProvider(LLMProvider):
    """Scripted investigation: exercises the full tool loop deterministically,
    then builds the final JSON from the tool results it actually received."""

    name = "mock"

    def __init__(self):
        self._step = 0

    # -- helpers to read prior tool results out of the message history
    @staticmethod
    def _tool_result(messages: list, tool_name: str) -> Optional[dict]:
        for m in reversed(messages):
            if m.get("role") == "tool" and m.get("name") == tool_name:
                try:
                    return json.loads(m["content"])
                except (json.JSONDecodeError, KeyError):
                    return None
        return None

    def chat(self, messages: list, tools: list) -> dict:
        self._step += 1
        call = lambda name, args: {"content": None, "tool_calls": [
            {"id": f"mock-{self._step}", "name": name, "arguments": json.dumps(args)}]}

        if self._step == 1:
            return call("get_error_summary", {})
        if self._step == 2:
            return call("get_source_stats", {})
        if self._step == 3:
            summary = self._tool_result(messages, "get_error_summary") or {}
            groups = summary.get("groups") or []
            if groups and groups[0]["sample_line_numbers"]:
                return call("get_context_window",
                            {"line_number": groups[0]["sample_line_numbers"][0], "n": 5})
            return call("search_logs", {"pattern": "error|warn|fail"})
        # step 4+: write the final answer from what the tools returned
        return {"content": json.dumps(self._final_answer(messages)), "tool_calls": None}

    def _final_answer(self, messages: list) -> dict:
        summary = self._tool_result(messages, "get_error_summary") or {}
        groups = summary.get("groups") or []
        error_lines = summary.get("total_error_lines", 0)

        if not groups:
            return {"overall_status": "healthy" if error_lines == 0 else "degraded",
                    "incidents": []}

        # merge groups that belong to the same playbook story (e.g. pool
        # exhaustion + its timeout cascade) into at most 3 incidents
        incidents, used_titles = [], {}
        for g in groups:
            # triage rule: occasional warnings are normal operations, not incidents
            if g["level"] == "WARNING" and g["count"] < 3:
                continue
            sample = g.get("sample_message") or g["message_signature"]
            title, solutions = _playbook_lookup(f"{g['message_signature']} {sample}")
            title = title or f"Repeated {g['level'].lower()}s: {sample[:60]}"
            if title in used_titles:
                inc = used_titles[title]
                inc["_count"] += g["count"]
                inc["affected_sources"] = sorted(set(inc["affected_sources"]) | set(g["sources"]))
                inc["_lines"].extend(g["sample_line_numbers"][:2])
                # widen the window (string compare is fine within one log's format)
                if g["first_seen"] and (not inc["first_seen"] or g["first_seen"] < inc["first_seen"]):
                    inc["first_seen"] = g["first_seen"]
                if g["last_seen"] and (not inc["last_seen"] or g["last_seen"] > inc["last_seen"]):
                    inc["last_seen"] = g["last_seen"]
                continue
            if len(incidents) == 3:
                continue  # cap new incidents, but keep scanning so cascades still merge
            inc = {
                "title": title,
                "severity": ("critical" if g["level"] == "CRITICAL" or g["count"] >= 5
                             else "high" if g["level"] == "ERROR" else "medium"),
                "confidence": 0.9 if g["count"] >= 3 else 0.7,
                "_count": g["count"],
                "_signature": sample,
                "_lines": list(g["sample_line_numbers"]),
                "affected_sources": g["sources"],
                "first_seen": g["first_seen"],
                "last_seen": g["last_seen"],
                "possible_solutions": solutions,
            }
            used_titles[title] = inc
            incidents.append(inc)

        for inc in incidents:
            src = ", ".join(inc["affected_sources"]) or "the logs"
            window = (f" between {inc['first_seen']} and {inc['last_seen']}"
                      if inc["first_seen"] else "")
            inc["human_explanation"] = (
                f"The logs show {inc['_count']} occurrence(s) of this problem "
                f"affecting {src}{window}. The recurring message looks like: "
                f"\"{inc['_signature'][:120]}\". This pattern usually means the "
                f"service could not do its normal work and requests started failing. "
                f"The cited lines below are the concrete evidence.")
            inc["evidence"] = [{"line_number": n,
                                "why_relevant": "Occurrence of the failing pattern this incident is based on."}
                               for n in dict.fromkeys(inc["_lines"])][:4]
            for k in ("_count", "_signature", "_lines"):
                inc.pop(k)

        has_critical = any(i["severity"] == "critical" for i in incidents)
        status = ("critical" if has_critical
                  else "degraded" if error_lines else "healthy")
        return {"overall_status": status, "incidents": incidents}


# -------------------------------------------------------------------- picker

def get_provider(mock: Optional[bool] = None) -> LLMProvider:
    """--mock flag wins; else ROSETTA_PROVIDER env (mock|azure); else azure if
    configured, else mock (so a fresh clone always works)."""
    if mock:
        return MockProvider()
    env = os.getenv("ROSETTA_PROVIDER", "").lower()
    if env == "mock":
        return MockProvider()
    if env == "azure":
        return AzureOpenAIProvider()
    if os.getenv("AZURE_OPENAI_API_KEY"):
        return AzureOpenAIProvider()
    return MockProvider()
