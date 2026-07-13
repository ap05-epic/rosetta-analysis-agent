# INTEGRATION.md — Merge the Rosetta Analysis Agent into `rosetta-log-analyzer`

**Audience: GitHub Copilot CLI (or any coding agent) executing inside the
`rosetta-log-analyzer` monorepo.** You need no context beyond this file.
Execute the steps in order. Every step has a "verify" check — do not continue
past a failed check; stop and report which step failed and its output.

## 0. Context you must assume (do not re-derive)

- The monorepo you are standing in is a GitLab repo with this layout:
  - `classifier/` — Reed's FastAPI regex parser (`__init__.py`, `regex.py`, `types.py`).
    Runs with: `uvicorn classifier.regex:app --reload --host 0.0.0.0 --port 8000`.
    Endpoints: `GET /health` → `{"status":"ok"}`; `POST /classify` takes a log
    file as multipart form data (field name `file`) and currently returns
    `{"filename": "<name>", "status": "PASS|FAIL|UNKNOWN"}`. CORS allows
    localhost:3000.
  - `client/` — Next.js + TypeScript UI on port 3000, with directories
    `app`, `components`, `hooks`, `lib`, `mock`, `public`, `types`. The UI is
    currently built against mock data in `client/mock/`.
  - `requirements.txt` at the repo root (single Python dependency file).
- Python 3.10+ is the target runtime.
- **Port assignments (fixed, do not change):** classifier = 8000,
  **agent = 8001**, UI = 3000.
- The source you are integrating is a sibling directory (this package, cloned
  from GitHub — referred to below as `$SRC`, the directory containing this
  INTEGRATION.md). It contains `agent/`, `tests/`, `requirements.txt`,
  `README.md`.
- The agent is self-contained: it imports nothing from `classifier/` or
  `client/`. It talks to them only over HTTP contracts described here.

## 1. Copy the package

1. Copy `$SRC/agent/` to the repo root as a top-level `agent/` directory,
   sibling of `classifier/` and `client/`. Copy the whole tree, including
   `agent/AGENT.md`, `agent/skills/`, `agent/schema/`, `agent/samples/`.
2. Copy `$SRC/tests/test_agent.py` into the repo:
   - If the repo already has a `tests/` directory, copy the file in as
     `tests/test_agent.py`.
   - If not, create `tests/` at the repo root and copy it there.
3. Do NOT copy `$SRC/README.md` over the repo README. If the repo README has
   no agent section, append the "Quickstart" and "API (port 8001)" sections
   from `$SRC/README.md` under a heading `## Analysis agent (agent/)`.

**Verify:** `ls agent/` shows `api.py core.py contracts.py adapters.py
tools.py providers.py skill_loader.py __main__.py AGENT.md skills schema
samples __init__.py`.

## 2. Merge dependencies into the root requirements.txt

The agent needs exactly these packages:

```
fastapi
uvicorn
pydantic>=2
openai
python-multipart
pytest
rich
```

For each line: if the root `requirements.txt` already contains that package
(any version spec), keep the existing line and do not duplicate it. Otherwise
append the line. `fastapi`, `uvicorn`, `pydantic`, and `python-multipart` are
very likely already present because of `classifier/`. Do not remove or loosen
any existing pin. Note: the agent uses Pydantic v2 APIs (`model_dump`,
`model_json_schema`) — if the root file pins `pydantic<2`, stop and report
this conflict instead of changing the pin silently.

Then install: `pip install -r requirements.txt`

**Verify:** `python -c "import fastapi, pydantic, openai, multipart, rich; import pydantic; assert pydantic.VERSION.startswith('2')"` exits 0.

## 3. Prove the agent works standalone (no credentials needed)

Run, from the repo root:

```bash
python -m agent demo --mock
```

**Verify:** it prints a report containing `CRITICAL` and
`Database connection pool exhaustion`, and exits 0.

```bash
python -m pytest tests/test_agent.py -q
```

**Verify:** all tests pass (11 passed). If the repo has its own pytest config
that changes rootdir/imports and collection fails, run
`python -m pytest tests/test_agent.py -q --rootdir=.` from the repo root.

## 4. Give the UI team the fixture immediately

Copy the committed example output into the UI's mock data so the frontend can
build against the real contract before any live wiring:

```bash
cp agent/schema/example_analysis.json client/mock/analysis.example.json
```

Also copy the JSON Schema next to it for reference (optional but helpful):

```bash
cp agent/schema/analysis_result.schema.json client/mock/analysis_result.schema.json
```

If `client/types/` contains hand-written TypeScript types, do not overwrite
anything; instead tell the UI team the shape is: `AnalysisResult { analysis_id,
generated_at, log_source, overall_status: "critical"|"degraded"|"healthy"|"inconclusive",
stats: {total_lines, error_lines, warning_lines}, incidents: Incident[] (max 3) }`,
`Incident { title, severity: "critical"|"high"|"medium"|"low", confidence: number 0-1,
human_explanation, possible_solutions: string[] (1-3), evidence: {line_number,
raw_text, timestamp|null, source|null, why_relevant}[], affected_sources: string[],
first_seen|null, last_seen|null }`.

**Verify:** `python -c "import json; json.load(open('client/mock/analysis.example.json'))"` exits 0.

## 5. Run all three services together

Three terminals (or background processes), all from the repo root:

```bash
# terminal 1 — classifier (Reed's parser)
uvicorn classifier.regex:app --reload --host 0.0.0.0 --port 8000

# terminal 2 — analysis agent (this package)
uvicorn agent.api:app --reload --host 0.0.0.0 --port 8001

# terminal 3 — UI
cd client && npm install && npm run dev
```

To run the agent against real Azure OpenAI instead of the mock, export
`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`
(and optionally `AZURE_OPENAI_API_VERSION`) in terminal 2 before starting it.
With no credentials set it falls back to the deterministic mock provider, and
any request can force mock mode with `?mock=true` — integration and demos work
credential-free.

## 6. Wire the UI — two supported options

The agent's `POST /analyze` on port 8001 accepts BOTH input kinds, so the UI
can wire up either way without agent changes. CORS for
`http://localhost:3000` is already configured in `agent/api.py` (same
convention as the classifier).

**Option A — two calls (classifier first, then agent):**
1. UI uploads the log file to the classifier as today:
   `POST http://localhost:8000/classify` (multipart, field `file`).
2. UI forwards the classifier's JSON response body, unmodified, to
   `POST http://localhost:8001/analyze` with header
   `Content-Type: application/json`.
3. Today the classifier returns only `{"filename","status"}` — the agent
   accepts that and returns an honest low-confidence `AnalysisResult`. When
   Reed's parser starts returning per-entry JSON
   (`{"entries":[{time,file,status,description,...}]}`), the SAME forwarding
   code starts producing full root-cause analyses. No UI change needed.

**Option B — one call (raw file straight to the agent):**
- UI posts the uploaded log file directly to
  `POST http://localhost:8001/analyze` as multipart form data, field name
  `file` (identical shape to the `/classify` call, just port 8001). The
  agent's built-in log-agnostic parser handles raw text itself. This is the
  recommended demo path because it produces full analyses today.

Either way, the response the UI renders is exactly the shape of
`client/mock/analysis.example.json`.

## 7. Verification checklist (run every command; compare to expected)

```bash
# 7.1 classifier is up
curl -s http://localhost:8000/health
# expected: {"status":"ok"}

# 7.2 agent is up
curl -s http://localhost:8001/health
# expected: {"status":"ok"}

# 7.3 raw-file path (Option B): full analysis from a bundled incident sample
curl -s -F "file=@agent/samples/db_pool_exhaustion.log" "http://localhost:8001/analyze?mock=true"
# expected: HTTP 200, JSON with "overall_status": "critical",
# "stats": {"total_lines": 30, "error_lines": 13, "warning_lines": 4},
# incidents[0].title == "Database connection pool exhaustion",
# every incidents[].evidence[].line_number is an integer that exists in the file.

# 7.4 parser-JSON path (Option A future shape)
curl -s -H "Content-Type: application/json" -d @agent/samples/example_parsed.json "http://localhost:8001/analyze?mock=true"
# expected: HTTP 200, "overall_status": "degraded",
# incidents[0].title == "Dependency unreachable",
# incidents[0].affected_sources == ["auth-service","token-store"].

# 7.5 parser-JSON path (Option A current minimal shape)
curl -s -H "Content-Type: application/json" -d '{"filename":"x.log","status":"FAIL"}' "http://localhost:8001/analyze?mock=true"
# expected: HTTP 200, "overall_status": "degraded",
# incidents[0].title == "Classifier flagged this log as FAIL", confidence <= 0.5.

# 7.6 healthy log produces no false alarms
curl -s -F "file=@agent/samples/healthy_run.log" "http://localhost:8001/analyze?mock=true"
# expected: "overall_status": "healthy", "incidents": [].

# 7.7 live end-to-end chain (Option A, real classifier in the middle)
curl -s -F "file=@agent/samples/db_pool_exhaustion.log" http://localhost:8000/classify > /tmp/classify.json
curl -s -H "Content-Type: application/json" -d @/tmp/classify.json http://localhost:8001/analyze?mock=true
# expected: HTTP 200 AnalysisResult (low-confidence while /classify is minimal;
# becomes a full analysis automatically once /classify returns entries).

# 7.8 tests still green in the monorepo
python -m pytest tests/test_agent.py -q
# expected: 11 passed

# 7.9 UI smoke test: open http://localhost:3000, upload
# agent/samples/db_pool_exhaustion.log through whichever wiring option was
# implemented, and confirm the rendered incident list matches 7.3's JSON.
```

## 8. Commit

Single commit on a feature branch, message:
`feat(agent): add Rosetta analysis agent (FastAPI :8001 + CLI, mock + Azure providers)`.
Include: `agent/` (all files), `tests/test_agent.py`, the requirements.txt
merge, and the two files copied into `client/mock/`. Do not modify anything
inside `classifier/` or the rest of `client/`.

## Troubleshooting

- `ModuleNotFoundError: agent` — you are not running from the repo root, or
  `agent/__init__.py` was not copied.
- `422 multipart request must include a 'file' field` — the form field must be
  named exactly `file`, matching the classifier's convention.
- CORS errors in the browser — the UI must call `http://localhost:8001`, and
  the agent must be started on port 8001 (the allowlist covers
  localhost:3000 and 127.0.0.1:3000).
- Result says `inconclusive` with "could not be reached" — Azure env vars are
  set but wrong/unreachable from the pod. Unset them or fix them; mock mode
  (`?mock=true`, `--mock`, or `ROSETTA_PROVIDER=mock`) never needs network.
- Windows consoles mangling box characters in `python -m agent demo` — output
  is ASCII-safe; if it still looks wrong, use
  `python -m agent analyze --input agent/samples/db_pool_exhaustion.log --output analysis.json --mock`
  and inspect the JSON directly.
