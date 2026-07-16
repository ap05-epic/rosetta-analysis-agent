# COPILOT_PROMPTS.md — exact prompts for GitHub Copilot CLI

Setup on the dev pod (once): clone/copy this package as a SIBLING of the
monorepo, then start Copilot from the monorepo root:

```bash
cd /projects
git clone https://github.com/ap05-epic/rosetta-analysis-agent.git   # or copy the folder up
cd /projects/rosetta-log-analyzer
copilot
```

Run the prompts one at a time, in order. Review each result before the next.
All work happens on the already-checked-out `llm-implementaion` branch; the
prompts tell Copilot to preserve your uncommitted changes and never push.

---

## Prompt 1 — backend: merge the agent package

```
You are in the rosetta-log-analyzer monorepo root, on branch llm-implementaion,
which has pre-existing uncommitted modifications (at least LAUNCH.md and
client/next.config.ts). Preserve those modifications exactly — never stash,
revert, or discard them. A self-contained Python package sits at
../rosetta-analysis-agent — call it $SRC.

Open $SRC/INTEGRATION.md and execute it literally, top to bottom (sections 1,
2, 2b, 3, 4, 5, then verification section 7 items 7.1 through 7.8). Rules:

1. Follow the steps in order. Every step has a "Verify" check — run it and
   confirm the expected output before moving on.
2. If any verify check fails, STOP. Do not improvise a fix. Report the step,
   the exact command, and its full output.
3. Do not modify anything inside classifier/ or client/ except the two fixture
   files section 4 copies into client/mock/.
4. Ports are fixed: classifier 8000, agent 8001, UI 3000.
5. Section 2b: ensure .env is gitignored, then create the root .env with
   placeholder values unless real ones are already present. Never print the
   value of any key, and never commit .env.
6. Stay on llm-implementaion. Commit exactly as section 8 specifies —
   only the files that section lists, leaving the pre-existing uncommitted
   changes uncommitted. Do NOT push.
7. Finish by printing a table: step | command | expected | actual | pass/fail.

Section 0 of INTEGRATION.md is the repo context to assume — trust it over
your own exploration if they conflict.
```

## Prompt 2 — frontend: wire the UI to the agent

```
Same repo, same branch (llm-implementaion). Prompt 1 is done: the agent/
package is merged and python3 -m uvicorn agent.api:app --port 8001 works.
Source package: ../rosetta-analysis-agent = $SRC.

Open $SRC/UI_INTEGRATION.md and execute Phases A, B, and C exactly. That file
quotes current repo code and gives exact replacement code — prefer its diffs
verbatim; if a quoted "current" snippet no longer matches the file, adapt to
the same intent and flag it in your report. Rules:

1. Obey the file's "Ground rules": preserve the pre-existing uncommitted
   changes in LAUNCH.md and client/next.config.ts (build on top of them);
   heed client/AGENTS.md (Next 16 canary — check node_modules/next/dist/docs
   before using any Next API not shown in the diffs); every next command
   needs --webpack.
2. The proxy pattern is Next rewrites. Do not create API route handlers, and
   never call localhost:8000/8001 from browser code.
3. The demo flow (isDemoScenario / runDemoAnalysisProgress) must remain
   byte-identical in behavior.
4. Run each phase's Verify gate before starting the next phase. On failure,
   STOP and report the phase, command, and full output.
5. Commit on llm-implementaion as
   "feat(client): wire UI to analysis agent via /api/agent rewrite".
   Do NOT push.
6. Finish with the pass/fail table for every Verify you ran, plus a list of
   every file you created or modified.
```

## Prompt 3 — frontend polish: evidence, confidence, stats

```
Same repo, same branch (llm-implementaion). Prompts 1 and 2 are done: the UI
fills its cards from the agent via the /api/agent rewrite. Source package:
../rosetta-analysis-agent = $SRC.

Execute Phase D and Phase E of $SRC/UI_INTEGRATION.md exactly: the new
EvidenceCard (code provided verbatim), the confidence badge on SeverityCard,
the stats chips on SummaryCard, the optional "other findings" strip, then the
Phase E checklist (tsc, next build --webpack, boot, curl check).

Rules: additive changes only — do not restructure existing components; mirror
the existing card styling and dark-mode variants exactly; no new npm
dependencies. Run every Verify; STOP and report on any failure. Commit on
llm-implementaion as
"feat(client): evidence, confidence and stats presentation for analysis results".
Do NOT push. Finish with the verify pass/fail table and a short note per
visual change.
```

## After the three prompts

Review, then push yourself:

```bash
git log --oneline -5        # expect the 3 new commits on llm-implementaion
git push origin llm-implementaion
```

Only you put the REAL LLM key in place (Copilot uses placeholders):

```bash
# edit /projects/rosetta-log-analyzer/.env → real LLM_BASE_URL + LLM_API_KEY
./scripts/boot.sh --skip-install     # restart so the agent picks it up
curl -s -F "file=@agent/samples/db_pool_exhaustion.log" http://localhost:8001/analyze | head -c 400
# live GPT-5.4 analysis JSON = wired correctly
```

If a phase went sideways, each prompt's commit is independent —
`git reset --hard HEAD~1` rolls back exactly one phase (your pre-existing
uncommitted files are never part of those commits).

## One-liner reference (for chat follow-ups with Copilot)

- Re-verify backend only: `Run section 7 of ../rosetta-analysis-agent/INTEGRATION.md items 7.1–7.8 and print the pass/fail table. Change nothing.`
- Re-verify frontend only: `Run Phase E of ../rosetta-analysis-agent/UI_INTEGRATION.md and print the results. Change nothing.`
- Agent misbehaving live? `curl -s -F "file=@agent/samples/db_pool_exhaustion.log" "http://localhost:8001/analyze?mock=true"` — if mock works but live does not, the problem is the LLM endpoint/env, not the pipeline; check /tmp/rla-agent.log.
