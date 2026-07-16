# Rosetta Analysis Agent

The LLM/agent stage of the Rosetta pipeline:

```
pipeline logs -> regex parser (classifier/) -> per-entry JSON -> [ THIS AGENT ] -> AnalysisResult JSON -> Next.js UI (client/)
```

Given a parsed log (or a raw log file — it has its own fallback parser), the
agent investigates via tools (error summary, context windows, per-source
stats, regex search), then returns a structured, evidence-cited incident
report: what went wrong, in plain English, with concrete next steps.

Anti-hallucination by construction: the model never sees the raw log (only
condensed tool results), every cited line number is cross-checked against the
input and fabricated citations are dropped, stats are computed from the data
rather than taken from the model, and "the evidence is insufficient" is a
first-class answer (`overall_status: "inconclusive"`).

## Quickstart (zero credentials)

```bash
pip install -r requirements.txt

# end-to-end demo on a bundled incident, offline deterministic mock LLM
python -m agent demo --mock

# other bundled scenarios
python -m agent demo --mock --sample bad_deploy
python -m agent demo --mock --sample healthy

# run the tests
pytest -q
```

`--mock` uses a deterministic provider that drives the same tool loop with no
network. Everything below also works with `--mock` / `?mock=true`.

## Live LLM (Azure OpenAI-compatible endpoint)

The primary path is any OpenAI-compatible base URL — including Azure's
`/openai/v1/` surface. Set these (env vars, or a `.env` file in the directory
you start the service from — it is auto-loaded and never overrides real env):

| Variable | Example |
|---|---|
| `LLM_BASE_URL` | `https://my-resource.openai.azure.com/openai/v1/` |
| `LLM_API_KEY` | `...` |
| `LLM_MODEL` | `gpt-5.4` (optional, this is the default; on Azure this is the deployment name) |
| `LLM_REASONING_EFFORT` | `low` (optional default; keeps GPT-5-family models fast — set empty to disable sending it) |

The classic Azure deployment API is also supported via `AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`.

Provider selection: `--mock` flag wins; otherwise
`ROSETTA_PROVIDER=mock|openai|azure`; otherwise `LLM_BASE_URL`+`LLM_API_KEY`;
otherwise `AZURE_OPENAI_API_KEY`; otherwise mock. LLM calls request
temperature 0.1; if the model rejects the parameter (GPT-5-family reasoning
models), the call is retried without it automatically.

## API (port 8001)

```bash
uvicorn agent.api:app --reload --host 0.0.0.0 --port 8001
```

Ports: classifier owns **8000**, this agent owns **8001**, the UI owns **3000**
(CORS for localhost:3000 is preconfigured).

- `GET /health` → `{"status": "ok"}`
- `POST /analyze` → `AnalysisResult`. Accepts either:
  - `application/json` — the parser's output. Both the future per-entry shape
    `{"entries": [...]}` and the current minimal `{"filename": ..., "status": "PASS|FAIL|UNKNOWN"}`
    are handled (the minimal shape yields an honest low-confidence result).
  - `multipart/form-data` with a `file` field — a raw log file; the built-in
    log-agnostic fallback parser handles mixed/unknown formats.
  - Append `?mock=true` to force the offline provider per request.

```bash
curl -F "file=@agent/samples/db_pool_exhaustion.log" "http://localhost:8001/analyze?mock=true"
curl -H "Content-Type: application/json" -d @agent/samples/example_parsed.json "http://localhost:8001/analyze?mock=true"
```

## CLI

```bash
python -m agent analyze --input agent/samples/db_pool_exhaustion.log --output analysis.json --mock
python -m agent analyze --input agent/samples/example_parsed.json --mock   # parser-JSON input
python -m agent demo --mock                                                # pretty terminal report
```

`--input` takes either a raw `.log` file or a parsed `.json` file; output is
the same `AnalysisResult` JSON the API returns.

## Contracts

- Output schema: [agent/schema/analysis_result.schema.json](agent/schema/analysis_result.schema.json)
- Example output (UI fixture): [agent/schema/example_analysis.json](agent/schema/example_analysis.json)

`AnalysisResult` = `analysis_id`, `generated_at`, `log_source`,
`overall_status` (critical/degraded/healthy/inconclusive), `stats`
(total/error/warning line counts), and up to 3 `incidents`, each with `title`,
`severity`, `confidence`, a 2–4 sentence `human_explanation`, 1–3
`possible_solutions`, verified `evidence` (line number + raw text + why it
matters), `affected_sources`, and a `first_seen`/`last_seen` window.

## Layout

```
agent/
  AGENT.md          system prompt: role, investigation procedure, evidence rules
  skills/           composable prompt modules (triage, root cause, fixes, output)
  skill_loader.py   deterministic AGENT.md + skills concatenation
  contracts.py      ParsedLog (input) and AnalysisResult (output) models
  adapters.py       3 input paths: parser JSON / minimal classify / raw text fallback
  tools.py          the 4 investigation tools + OpenAI tool schemas
  providers.py      AzureOpenAI + deterministic mock provider
  core.py           8-step agentic loop, validation retry, evidence verification
  api.py            FastAPI service (port 8001)
  __main__.py       CLI (analyze / demo)
  schema/           committed JSON Schema + example fixture
  samples/          3 synthetic scenarios with known ground truth + parsed-JSON example
tests/              contracts, adapters, fallback parser, golden mock runs
```

Integrating into the team monorepo? [INTEGRATION.md](INTEGRATION.md) merges
the backend package, [UI_INTEGRATION.md](UI_INTEGRATION.md) wires the Next.js
client, and [COPILOT_PROMPTS.md](COPILOT_PROMPTS.md) has the exact prompts to
drive both with GitHub Copilot CLI.
