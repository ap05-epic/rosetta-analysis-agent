# UI_INTEGRATION.md — Wire the Next.js client to the analysis agent

**Audience: GitHub Copilot CLI (or any coding agent) executing inside the
`rosetta-log-analyzer` monorepo, AFTER `INTEGRATION.md` has been completed**
(the `agent/` package exists at repo root and `uvicorn agent.api:app --port
8001` works). Execute phases in order; each ends with a verify gate — stop and
report on failure.

## Ground rules (apply to every phase)

- READ before you write: open `client/app/page.tsx`, everything in
  `client/components/`, `client/types/analysis.ts`, `client/mock/analysis.ts`,
  and `client/lib/activityProgress.ts` first. Match their naming, styling
  (Tailwind v4 utility classes via the existing `cn.ts` helper), and component
  conventions. Keep dark mode working: any new markup needs `dark:` variants
  consistent with the existing cards.
- Do not rename or delete existing exports; extend them.
- No new npm dependencies. No changes outside `client/` in this file's scope.
- This platform's Next.js (16.x canary) has WASM bindings only — any `next`
  command you run must include `--webpack`.
- The browser must ONLY ever call same-origin URLs (`/api/...`). The dev-pod
  proxy (`https://<pod>.cloud.ubs.net/proxy/3000/...`) breaks direct
  browser→:8000/:8001 calls. All agent traffic goes through the route handler
  built in Phase A, which talks to `127.0.0.1:8001` server-side.
- `AGENT_URL` is a server-only env var: never prefix it with `NEXT_PUBLIC_`,
  never read it in a client component.

## Phase A — same-origin proxy route

1. Create `client/app/api/analyze/route.ts`:
   - `export const dynamic = "force-dynamic";` (no caching).
   - `POST` handler:
     - Agent base: `const AGENT = process.env.AGENT_URL ?? "http://127.0.0.1:8001";`
     - Forward the `mock` query param if present:
       `/analyze` or `/analyze?mock=true`.
     - If the incoming `content-type` starts with `multipart/`:
       `const form = await request.formData();` then
       `fetch(url, { method: "POST", body: form, signal: AbortSignal.timeout(180_000) })`.
       IMPORTANT: do NOT copy the incoming `Content-Type` header onto the
       outgoing request — `fetch` must set its own multipart boundary.
     - Otherwise: forward the raw body with
       `headers: { "content-type": "application/json" }`.
     - Return the upstream JSON and status code unchanged. On network
       failure/timeout, return status 502 with
       `{ "error": "analysis agent unreachable on port 8001" }`.
2. Add to `client/.env.local` (create the line, keep existing content):
   `AGENT_URL=http://127.0.0.1:8001`

**Verify (agent must be running on 8001, client dev server on 3000):**

```bash
curl -s -F "file=@agent/samples/db_pool_exhaustion.log" "http://localhost:3000/api/analyze?mock=true"
# expected: HTTP 200, JSON with "overall_status": "critical" and
# incidents[0].title == "Database connection pool exhaustion"
```

## Phase B — types and mapping

1. Add the agent's response types to `client/types/analysis.ts` (do not remove
   existing types — the current UI card types stay). The authoritative shape is
   `client/mock/analysis.example.json` (copied there by INTEGRATION.md step 4;
   source of truth: `agent/schema/analysis_result.schema.json`):

   ```ts
   export type OverallStatus = "critical" | "degraded" | "healthy" | "inconclusive";
   export type IncidentSeverity = "critical" | "high" | "medium" | "low";
   export interface AgentEvidence { line_number: number; raw_text: string;
     timestamp: string | null; source: string | null; why_relevant: string; }
   export interface AgentIncident { title: string; severity: IncidentSeverity;
     confidence: number; human_explanation: string; possible_solutions: string[];
     evidence: AgentEvidence[]; affected_sources: string[];
     first_seen: string | null; last_seen: string | null; }
   export interface AgentAnalysisResult { analysis_id: string; generated_at: string;
     log_source: string; overall_status: OverallStatus;
     stats: { total_lines: number; error_lines: number; warning_lines: number };
     incidents: AgentIncident[]; }
   ```

2. Create `client/lib/mapAnalysis.ts` exporting
   `mapAnalysis(r: AgentAnalysisResult): <the existing UI card model>` — return
   whatever type `client/mock/analysis.ts` currently produces so ALL existing
   card components keep working untouched. Mapping rules (top incident =
   `r.incidents[0]`, they arrive sorted most-severe first):

   | UI field | Source |
   |---|---|
   | issue summary | top incident's `title`; if `incidents.length > 1` append ` (+N related finding${N>1?"s":""})`; healthy → `"No issues found — this log looks healthy."`; inconclusive with no incidents → `"Analysis inconclusive."` |
   | severity | top incident `severity` mapped onto the EXISTING severity union in `types/analysis.ts` (`critical→Critical`-equivalent, `high→High`, `medium→Medium`, `low→Low`, matching its exact casing/values). Healthy run → the union's lowest/none value; extend the union with one value ONLY if it has nothing suitable for "no issues". |
   | root cause | top incident `human_explanation`; healthy → same healthy sentence; if the run is `inconclusive`, the incident's explanation already says why — use it verbatim. |
   | recommendations | top incident `possible_solutions` (already 1–3 imperative strings); healthy → `[]`. |

   Also export the extras Phase D renders (returning them alongside is fine
   even before Phase D uses them): `confidence` (0–1), `evidence` (array),
   `stats`, `affectedSources`, `otherIncidents` (`incidents.slice(1)`),
   `overallStatus`, `logSource`.

**Verify:** `cd client && npx tsc --noEmit` exits 0.

## Phase C — wire the real flow

1. Find where the "Explain Issue" button (`AnalyzeButton.tsx` / `page.tsx`)
   currently triggers the mock flow (`mock/analysis.ts` + the timed
   `lib/activityProgress.ts` animation). Replace the data source, keep the UX:
   - Build a job list on click: each uploaded file (the `FileUpload` component
     allows up to 5) becomes one job; non-empty pasted text (`TextPasteArea`)
     becomes one additional job as
     `new File([text], "pasted.log", { type: "text/plain" })`.
   - If there are zero jobs, keep whatever empty-state behavior exists today.
   - For each job SEQUENTIALLY (keeps the activity feed truthful and the pod
     load sane): `const fd = new FormData(); fd.append("file", file);`
     `fetch("/api/analyze", { method: "POST", body: fd })` → parse as
     `AgentAnalysisResult` → `mapAnalysis`.
   - Store one result per job; render `AnalysisTabs` with one tab per result
     labeled by `log_source` (existing tab behavior for a single result stays).
2. Activity feed honesty: steps up to and including "Failure Detection
   Complete" may keep their existing timed animation, but "Calling AI Model"
   must only be marked complete when the LAST fetch resolves, and "Analysis
   Complete" only after results are mapped and set into state. On any request
   failure, mark the current step failed (add a minimal error visual to
   `ActivityStep` if none exists) and stop the feed.
3. Error UX: on non-200 or network error show an inline dismissible banner
   near the results area — text
   `"Analysis service unreachable — is the agent running on port 8001?"` for
   502/network, otherwise the `error` string from the response JSON. Do not
   clear previously rendered results.
4. "Try a demo" button: change it to POST the text of
   `agent/samples/db_pool_exhaustion.log` (bundle the string as a constant in
   `client/mock/` — do not fetch across the filesystem at runtime) to
   `/api/analyze?mock=true` and run the normal flow; if that request fails,
   fall back to the existing static `mock/analysis.ts` data so the demo can
   never die on stage.
5. Mock escape hatch: add `const USE_MOCK_AGENT = false;` at the top of the
   module that issues the fetches; when `true`, every request appends
   `?mock=true`. One flag to flip if the LLM endpoint dies mid-presentation.
   (The "Try a demo" button always uses `?mock=true` regardless of the flag.)

**Verify:**
- `cd client && npx tsc --noEmit` exits 0.
- With classifier+agent+client running: in the browser (through the pod proxy
  URL), upload `agent/samples/db_pool_exhaustion.log`, click Explain Issue →
  Summary/Severity/Root Cause/Recommendations cards fill with the pool-
  exhaustion analysis; activity feed completes; a `pipeline`-style tab shows
  the filename.
- Paste the pipeline ECONNREFUSED demo text into the paste box instead →
  cards fill (mock title mentions retries or an unreachable dependency).
- Upload `agent/samples/healthy_run.log` → healthy state, no fake incidents.
- Stop the agent process; click Explain Issue → red banner, no crash.

## Phase D — presentation polish (recommended, additive only)

The agent returns three things the current cards do not show, and they are
the differentiators of this project (evidence-cited, calibrated analysis):

1. **Evidence** — new `EvidenceCard.tsx` (mirror the card chrome of
   `RootCauseCard.tsx`): for each `evidence` item of the top incident render a
   monospace row `L{line_number}` + `raw_text` (truncate ~140 chars,
   `overflow-x-auto`) with `why_relevant` as smaller muted subtext. Collapsed
   by default behind a "Show evidence (N lines)" toggle if the list exceeds 3.
2. **Confidence** — a small percentage badge (`Math.round(confidence*100)%`)
   rendered next to the severity pill in `SeverityCard.tsx`, with a muted
   label "confidence".
3. **Stats chips** — under the issue summary, three small chips:
   `{total_lines} lines`, `{error_lines} errors`, `{warning_lines} warnings`
   (error chip red-tinted, warning amber, both with dark: variants).
4. **Other findings** — if `otherIncidents.length > 0`, a collapsed list under
   the main cards: severity dot + title + one-line explanation each.
5. If a healthy run renders, show a calm green success panel in place of the
   four cards ("No issues found — this log looks healthy.") rather than four
   empty boxes.

**Verify:** `npx tsc --noEmit` passes; re-run the Phase C browser checks and
confirm evidence lines shown for the pool sample match real line numbers from
the uploaded file (spot-check line 14 is a HikariPool error); dark mode still
renders correctly (toggle the existing theme control).

## Phase E — final checklist

```bash
# 1 type-check
cd client && npx tsc --noEmit
# 2 production build compiles (webpack is mandatory on this platform)
npx next build --webpack
# 3 same-origin route works end to end (agent running)
curl -s -F "file=@../agent/samples/db_pool_exhaustion.log" "http://localhost:3000/api/analyze?mock=true" | head -c 400
# expected: JSON starting with {"analysis_id": ... "overall_status": "critical"
```

Then commit on the feature branch:
`feat(client): wire UI to analysis agent via same-origin /api/analyze proxy`.
Do not push until the operator reviews.
