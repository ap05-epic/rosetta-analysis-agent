"""Contract, adapter, parser, and golden-run tests. Run: pytest -q"""

import json
from pathlib import Path

import pytest

from agent.adapters import from_raw_text, to_parsed_log
from agent.contracts import AnalysisResult, ParsedLog
from agent.core import analyze
from agent.providers import MockProvider

SAMPLES = Path(__file__).parent.parent / "agent" / "samples"
SCHEMA_DIR = Path(__file__).parent.parent / "agent" / "schema"


# ------------------------------------------------------------- contracts

def test_analysis_result_round_trip():
    fixture = json.loads((SCHEMA_DIR / "example_analysis.json").read_text(encoding="utf-8"))
    result = AnalysisResult.model_validate(fixture)          # parse
    again = AnalysisResult.model_validate_json(result.model_dump_json())  # round-trip
    assert again == result
    assert again.incidents, "fixture should contain at least one incident"
    assert all(i.evidence for i in again.incidents), "fixture incidents must cite evidence"


def test_committed_schema_matches_model():
    committed = json.loads((SCHEMA_DIR / "analysis_result.schema.json").read_text(encoding="utf-8"))
    assert committed == AnalysisResult.model_json_schema()


# -------------------------------------------------------------- adapters

def test_adapter_structured_json_with_aliases():
    data = json.loads((SAMPLES / "example_parsed.json").read_text(encoding="utf-8"))
    parsed = to_parsed_log(data)
    assert parsed.log_source == "auth_service.log"
    assert len(parsed.entries) == 8
    e = parsed.entries[3]
    assert e.level == "ERROR"                # "status": "ERROR" -> level
    assert e.source == "auth-service"        # "file" -> source
    assert e.time == "2026-07-10T09:14:11Z"  # "time" kept
    assert "token store unreachable" in e.message  # "description" -> message


def test_adapter_classifier_minimal():
    parsed = to_parsed_log({"filename": "x.log", "status": "FAIL"})
    assert parsed.classifier_status == "FAIL"
    assert parsed.entries == []
    result = analyze(parsed, provider=MockProvider())
    assert result.overall_status == "degraded"
    assert result.incidents[0].confidence <= 0.5  # honest: no lines, low confidence

    assert analyze(to_parsed_log({"filename": "y.log", "status": "PASS"}),
                   provider=MockProvider()).overall_status == "healthy"


def test_adapter_raw_text_and_rejects_garbage():
    parsed = to_parsed_log("hello world\nERROR something broke\n", log_source="t.log")
    assert isinstance(parsed, ParsedLog) and len(parsed.entries) == 2
    with pytest.raises(ValueError):
        to_parsed_log({"unexpected": "shape"})
    with pytest.raises(ValueError):
        to_parsed_log(12345)


# ------------------------------------------------------- fallback parser

def test_fallback_parser_on_mixed_format_sample():
    parsed = from_raw_text((SAMPLES / "db_pool_exhaustion.log").read_text(encoding="utf-8"))
    by_line = {e.line_number: e for e in parsed.entries}

    iso = by_line[14]  # ISO app log: pool exhausted ERROR
    assert iso.level == "ERROR" and iso.source == "payments-service"
    assert iso.time.startswith("2026-07-13T08:02:14")

    nginx = by_line[20]  # nginx access log with 504 -> ERROR by status heuristic
    assert nginx.level == "ERROR"

    syslog = by_line[10]  # syslog line -> postgres source, syslog timestamp
    assert syslog.source == "postgres" and syslog.time == "Jul 13 08:02:05"

    assert sum(1 for e in parsed.entries if e.level == "ERROR") >= 10


def test_fallback_parser_never_fails_on_unknown_format():
    weird = "!!! totally custom line ===\n<xml><no standard format/></xml>\n\n"
    parsed = from_raw_text(weird)
    assert len(parsed.entries) == 2          # blank line skipped
    assert all(e.raw for e in parsed.entries)  # raw always preserved


# ------------------------------------------------------------ golden run

def test_golden_mock_run_db_pool():
    parsed = to_parsed_log((SAMPLES / "db_pool_exhaustion.log").read_text(encoding="utf-8"),
                           log_source="db_pool_exhaustion.log")
    result = analyze(parsed, provider=MockProvider())

    assert result.overall_status == "critical"
    assert 1 <= len(result.incidents) <= 3
    top = result.incidents[0]
    assert "pool" in top.title.lower()
    assert top.severity == "critical"
    assert "payments-service" in top.affected_sources
    valid_lines = {e.line_number for e in parsed.entries}
    for inc in result.incidents:
        assert inc.evidence, "every incident must cite evidence"
        for ev in inc.evidence:
            assert ev.line_number in valid_lines      # no fabricated citations
            assert ev.raw_text == next(e.raw for e in parsed.entries
                                       if e.line_number == ev.line_number)
    # stats are computed from data, not taken from the model
    assert result.stats.total_lines == len(parsed.entries)


def test_golden_mock_run_healthy():
    parsed = to_parsed_log((SAMPLES / "healthy_run.log").read_text(encoding="utf-8"),
                           log_source="healthy_run.log")
    result = analyze(parsed, provider=MockProvider())
    assert result.overall_status == "healthy"
    assert result.incidents == []            # one benign warning is not an incident
    assert result.stats.error_lines == 0


def test_evidence_verification_drops_fabricated_lines():
    """A hostile/hallucinating provider citing line 999 must not survive."""
    class LyingProvider(MockProvider):
        def chat(self, messages, tools):
            return {"content": json.dumps({
                "overall_status": "degraded",
                "incidents": [{
                    "title": "Made-up incident", "severity": "high", "confidence": 0.95,
                    "human_explanation": "This cites a line that does not exist.",
                    "possible_solutions": ["Do nothing."],
                    "evidence": [{"line_number": 999, "why_relevant": "fabricated"}],
                    "affected_sources": [],
                }]}), "tool_calls": None}

    parsed = to_parsed_log("INFO all fine\nERROR one real error\n")
    result = analyze(parsed, provider=LyingProvider())
    inc = result.incidents[0]
    assert inc.evidence == []                # fake citation dropped
    assert inc.confidence <= 0.3             # and confidence knocked down


def test_provider_selection_from_llm_env(monkeypatch):
    from agent.providers import get_provider
    monkeypatch.setenv("LLM_BASE_URL", "https://example.openai.azure.com/openai/v1/")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("ROSETTA_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    p = get_provider()
    assert p.name == "openai-compat"
    assert p.model == "gpt-5.4"                      # default model
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4-mini")
    assert get_provider().model == "gpt-5.4-mini"
    monkeypatch.setenv("ROSETTA_PROVIDER", "mock")   # explicit override wins
    assert get_provider().name == "mock"
    assert get_provider(mock=True).name == "mock"    # flag beats everything


def test_dotenv_loader_never_overrides(tmp_path, monkeypatch):
    import os
    from agent.providers import _load_dotenv
    envfile = tmp_path / ".env"
    envfile.write_text(
        'LLM_BASE_URL="https://x.openai.azure.com/openai/v1/"\n'
        "# comment line\n"
        "OTEL_ENABLED=true\n"
        "not a kv line\n", encoding="utf-8")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OTEL_ENABLED", "false")      # pre-set env must win
    try:
        _load_dotenv(str(envfile))
        assert os.environ["LLM_BASE_URL"] == "https://x.openai.azure.com/openai/v1/"
        assert os.environ["OTEL_ENABLED"] == "false"
    finally:
        os.environ.pop("LLM_BASE_URL", None)
    _load_dotenv(str(tmp_path / "missing.env"))      # absent file is a no-op


def test_fallback_parser_on_ui_demo_format():
    """The exact format shown in the client's paste box demo."""
    text = (
        "2026-07-09T08:42:01.234Z [ERROR] pipeline.worker - Connection to "
        "postgres://db-prod:5432/rosetta refused (ECONNREFUSED)\n"
        "2026-07-09T08:42:01.235Z [ERROR] pipeline.worker - Retry attempt 1/3 after 2000ms\n"
        "2026-07-09T08:42:03.241Z [ERROR] pipeline.worker - Retry attempt 2/3 after 2000ms\n")
    parsed = to_parsed_log(text, log_source="pipeline.log")
    assert all(e.level == "ERROR" for e in parsed.entries)
    assert all(e.source == "pipeline.worker" for e in parsed.entries)
    result = analyze(parsed, provider=MockProvider())
    assert result.overall_status in ("critical", "degraded")
    titles = [i.title for i in result.incidents]
    assert any("retries" in t.lower() or "unreachable" in t.lower() for t in titles)
    assert all(i.evidence for i in result.incidents)


def test_unreachable_provider_gives_inconclusive():
    from agent.providers import LLMProvider, ProviderError

    class DeadProvider(LLMProvider):
        def chat(self, messages, tools):
            raise ProviderError("connection refused")

    result = analyze(to_parsed_log("ERROR boom\n"), provider=DeadProvider())
    assert result.overall_status == "inconclusive"
    assert "could not be reached" in result.incidents[0].human_explanation
