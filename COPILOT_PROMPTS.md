# COPILOT_PROMPTS.md — exact prompts for GitHub Copilot CLI

Setup on the dev pod (once): clone/copy this package as a SIBLING of the
monorepo, then start Copilot from the monorepo root:

```bash
cd /projects
git clone https://github.com/ap05-epic/rosetta-analysis-agent.git   # or scp the folder up
cd /projects/rosetta-log-analyzer
copilot
```

Run the prompts one at a time, in order. Review each result before the next.

---

## Prompt 1 — backend: merge the agent package

```
You are in the rosetta-log-analyzer monorepo root. A self-contained Python
package sits at ../rosetta-analysis-agent — call it $SRC.

Open $SRC/INTEGRATION.md and execute it literally, top to bottom (sections 1
through 5, plus verification section 7 items 7.1–7.8). Rules:

1. Follow the steps in order. Every step has a "Verify" check — run it and
   confirm the expected output before moving on.
2. If any verify check fails, STOP. Do not improvise a fix. Report the step,
   the exact command, and its full output.
3. Do not modify anything inside classifier/ or client/ except the two fixture
   files section 4 says to copy into client/mock/.
4. Ports are fixed: classifier 8000, agent 8001, UI 3000.
5. For section 2b: append the LLM_* lines to the existing root .env only if
   absent, using placeholder values if the real key is not already there.
   Never print the value of any key.
6. Work on a new branch named feat/analysis-agent. Commit as section 8
   specifies. Do NOT push.
7. Finish by printing a table: step | command | expected | actual | pass/fail.

Section 0 of INTEGRATION.md is the repo context to assume — trust it over
your own exploration if they conflict.
```

## Prompt 2 — frontend: wire the UI to the agent

```
You are in the rosetta-log-analyzer monorepo root, on branch
feat/analysis-agent (Prompt 1 already merged the agent/ package and it runs
on port 8001). The package source is at ../rosetta-analysis-agent = $SRC.

Open $SRC/UI_INTEGRATION.md and execute Phases A, B, and C exactly. Rules:

1. Obey the "Ground rules" section at the top of that file — especially:
   read client/app/page.tsx, all of client/components/, client/types/analysis.ts,
   client/mock/analysis.ts and client/lib/activityProgress.ts BEFORE writing
   anything, and match their conventions.
2. The browser must only call same-origin /api/analyze. Never fetch
   http://localhost:8000 or :8001 from browser code.
3. Every next command needs --webpack (WASM-only platform).
4. Run each phase's Verify gate before starting the next phase. On failure,
   STOP and report the phase, command, and full output.
5. Keep "Try a demo" working exactly as Phase C item 4 specifies (demo can
   never hard-fail).
6. Commit on feat/analysis-agent with message
   "feat(client): wire UI to analysis agent via same-origin /api/analyze proxy".
   Do NOT push.
7. Finish with the pass/fail table for every Verify you ran, plus a list of
   every file you created or modified.
```

## Prompt 3 — frontend polish: evidence, confidence, stats

```
Same repo, same branch (feat/analysis-agent). Prompts 1 and 2 are done: the
UI fills its cards from POST /api/analyze. Source package: ../rosetta-analysis-agent = $SRC.

Execute Phase D and Phase E of $SRC/UI_INTEGRATION.md exactly:
evidence card, confidence badge next to the severity pill, stats chips,
"other findings" list, healthy-run success panel, then the Phase E checklist
(tsc, next build --webpack, curl check).

Rules: additive changes only — do not restructure existing components; mirror
the existing card styling and dark-mode variants; no new npm dependencies.
Run every Verify; STOP and report on any failure. Commit as
"feat(client): evidence, confidence and stats presentation for analysis results".
Do NOT push. Finish with the verify pass/fail table and screenshots-worthy
notes on what changed visually.
```

## After the three prompts

You review the branch, then push and open the MR yourself:

```bash
git log --oneline main..feat/analysis-agent   # expect 3 commits
git push -u origin feat/analysis-agent
```

If something went sideways, each prompt's commit is independent — `git reset
--hard HEAD~1` rolls back exactly one phase.

## One-liner reference (for chat follow-ups with Copilot)

- Re-verify backend only: `Run section 7 of ../rosetta-analysis-agent/INTEGRATION.md items 7.1–7.8 and print the pass/fail table. Change nothing.`
- Re-verify frontend only: `Run Phase E of ../rosetta-analysis-agent/UI_INTEGRATION.md and print the results. Change nothing.`
- Flip to mock for a demo: `In the client module that calls /api/analyze, set USE_MOCK_AGENT = true, run npx tsc --noEmit, commit as "chore(client): demo mock mode".`
