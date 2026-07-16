# UI_INTEGRATION.md — Wire the Next.js client to the analysis agent

**Audience: GitHub Copilot CLI (or any coding agent) executing inside the
`rosetta-log-analyzer` monorepo, AFTER `INTEGRATION.md` has been completed**
(the `agent/` package exists at repo root and
`python3 -m uvicorn agent.api:app --host 0.0.0.0 --port 8001` works).
Execute phases in order; each ends with a verify gate — stop and report on
failure.

This file was written against the actual repo state (July 2026): it quotes
real file contents. If a quoted "current" snippet does not match what you
find, the repo moved — adapt the change to the same intent and say so in your
report instead of forcing the old text.

## Ground rules

- Stay on the current branch (`llm-implementaion`). Do NOT discard or revert
  existing uncommitted changes (LAUNCH.md and client/next.config.ts have local
  modifications that must survive).
- Heed `client/AGENTS.md`: this Next.js is 16.x canary — if you need any Next
  API beyond the exact diffs below, check `node_modules/next/dist/docs/`
  first. Every `next` command needs `--webpack` (WASM-only platform).
- The proxy pattern in this repo is **Next rewrites** (`/api/backend/:path*`
  → `http://localhost:8000/:path*` with `basePath` =
  `/projects/rosetta-log-analyzer`). The agent gets a second rewrite. Do NOT
  introduce API route handlers, and never call `http://localhost:8001`
  directly from browser code.
- No new npm dependencies. Match existing styling exactly: `ubs-card`
  sections, `#E60000` accents, `dark:border-[#7A7870]` etc., as used in the
  files you are editing.

## Phase A — plumbing (rewrite + boot script)

### A1. `client/next.config.ts` — add the agent rewrite

Add an `AGENT_PORT` const and a second rewrite, keeping everything else
byte-identical:

```ts
const BACKEND_PORT = process.env.APP_BACKEND_PORT ?? "8000";
const AGENT_PORT = process.env.APP_AGENT_PORT ?? "8001";
```

```ts
    async rewrites() {
      return [
        {
          source: "/api/backend/:path*",
          destination: `http://localhost:${BACKEND_PORT}/:path*`,
        },
        {
          source: "/api/agent/:path*",
          destination: `http://localhost:${AGENT_PORT}/:path*`,
        },
      ];
    },
```

### A2. `scripts/boot.sh` — teach the boot script about the agent

Read the script first, then mirror its existing port-8000 handling for 8001,
same style, same order:

1. Wherever it stops listeners on ports 3000 and 8000, also stop 8001
   (including the `--stop` variant).
2. Wherever it starts the backend
   (`python3 -m uvicorn classifier.regex:app ... --port 8000`, logging to
   `/tmp/rla-backend.log`), add the agent immediately after, started FROM THE
   REPO ROOT (it auto-reads `./.env` for LLM credentials):
   `python3 -m uvicorn agent.api:app --host 0.0.0.0 --port 8001`,
   logging to `/tmp/rla-agent.log`.
3. Wherever it writes `client/.env.local` with `NEXT_PUBLIC_API_BASE_URL`
   (value shaped like `<prefix>/api/backend`), add a sibling line
   `NEXT_PUBLIC_AGENT_BASE_URL` with the SAME prefix and `/api/agent` instead
   of `/api/backend`.
4. Add a health wait/check for `http://localhost:8001/health` wherever it
   checks the backend, if it does.

### A3. Verify

```bash
./scripts/boot.sh --skip-install
curl -s http://localhost:8000/health          # {"status":"ok"}
curl -s http://localhost:8001/health          # {"status":"ok"}
grep AGENT client/.env.local                  # NEXT_PUBLIC_AGENT_BASE_URL=.../api/agent
# through the Next rewrite (basePath included), mock forced:
curl -s -F "file=@agent/samples/db_pool_exhaustion.log" \
  "http://localhost:3000/projects/rosetta-log-analyzer/api/agent/analyze?mock=true" | head -c 300
# expected: JSON containing "overall_status": "critical"
```

## Phase B — types and mapper

### B1. `client/types/analysis.ts` — append agent wire types + optional card extras

Current file ends with `AnalysisResultsResponse`. APPEND (change nothing
existing):

```ts
// ---- Detail supplied by the analysis agent (optional on every result so
// ---- mock/demo and parser-only fallback paths are unaffected) ----

export interface EvidenceItem {
  lineNumber: number;
  rawText: string;
  whyRelevant: string;
}

export interface RelatedIncident {
  title: string;
  severity: Severity;
  explanation: string;
}

export interface AnalysisStats {
  totalLines: number;
  errorLines: number;
  warningLines: number;
}

// ---- Wire format returned by POST /api/agent/analyze (see
// ---- client/mock/analysis.example.json for a real example) ----

export type AgentOverallStatus =
  | "critical"
  | "degraded"
  | "healthy"
  | "inconclusive";

export type AgentSeverity = "critical" | "high" | "medium" | "low";

export interface AgentEvidence {
  line_number: number;
  raw_text: string;
  timestamp: string | null;
  source: string | null;
  why_relevant: string;
}

export interface AgentIncident {
  title: string;
  severity: AgentSeverity;
  confidence: number;
  human_explanation: string;
  possible_solutions: string[];
  evidence: AgentEvidence[];
  affected_sources: string[];
  first_seen: string | null;
  last_seen: string | null;
}

export interface AgentAnalysisResult {
  analysis_id: string;
  generated_at: string;
  log_source: string;
  overall_status: AgentOverallStatus;
  stats: {
    total_lines: number;
    error_lines: number;
    warning_lines: number;
  };
  incidents: AgentIncident[];
}
```

Then EXTEND the existing `AnalysisResult` interface (add fields, all
optional, keep the existing five):

```ts
export interface AnalysisResult {
  fileName: string;
  parserStatus?: ParserStatus;
  severity: Severity;
  summary: string;
  rootCause: string;
  recommendations: string[];
  confidence?: number;
  evidence?: EvidenceItem[];
  affectedSources?: string[];
  stats?: AnalysisStats;
  otherIncidents?: RelatedIncident[];
}
```

### B2. New file `client/lib/mapAnalysis.ts` — exact content

```ts
import type {
  AgentAnalysisResult,
  AgentSeverity,
  AnalysisResult,
  ParserStatus,
  Severity,
} from "@/types/analysis";

const severityMap: Record<AgentSeverity, Severity> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export function mapAgentAnalysis(
  agent: AgentAnalysisResult,
  fileName: string,
  parserStatus?: ParserStatus
): AnalysisResult {
  const stats = {
    totalLines: agent.stats.total_lines,
    errorLines: agent.stats.error_lines,
    warningLines: agent.stats.warning_lines,
  };

  const top = agent.incidents[0];

  if (!top) {
    const healthy = agent.overall_status === "healthy";
    return {
      fileName,
      parserStatus,
      severity: "Low",
      summary: healthy
        ? "No issues found — this log looks healthy."
        : "Analysis inconclusive — not enough evidence to name a root cause.",
      rootCause: healthy
        ? `Scanned ${stats.totalLines} lines: ${stats.errorLines} errors and ${stats.warningLines} warnings, nothing actionable.`
        : "The analysis engine could not reach a conclusion for this log.",
      recommendations: [],
      stats,
    };
  }

  const extra = agent.incidents.length - 1;

  return {
    fileName,
    parserStatus,
    severity: severityMap[top.severity],
    summary:
      extra > 0
        ? `${top.title} (+${extra} related finding${extra > 1 ? "s" : ""})`
        : top.title,
    rootCause: top.human_explanation,
    recommendations: top.possible_solutions.slice(0, 3),
    confidence: top.confidence,
    evidence: top.evidence.map((item) => ({
      lineNumber: item.line_number,
      rawText: item.raw_text,
      whyRelevant: item.why_relevant,
    })),
    affectedSources: top.affected_sources,
    stats,
    otherIncidents: agent.incidents.slice(1).map((incident) => ({
      title: incident.title,
      severity: severityMap[incident.severity],
      explanation: incident.human_explanation,
    })),
  };
}
```

### B3. Verify

`cd client && npx tsc --noEmit` exits 0.

## Phase C — wire `client/app/page.tsx`

The current non-demo flow in `runAnalysisProgress()` classifies each file
(`classifySingleFile` → `${API_BASE_URL}/classify`) and fills the cards with
canned text via `classifyResponseToAnalysis(...)`. Upgrade it: classifier
verdict stays (it feeds the `parserStatus` chip on `SeverityCard`), and the
agent supplies the real analysis, with the canned text demoted to per-file
fallback. The demo flow (`isDemoScenario` / `runDemoAnalysisProgress`) stays
untouched.

### C1. Add the agent base URL next to the existing `API_BASE_URL` const

```ts
const AGENT_BASE_URL =
  process.env.NEXT_PUBLIC_AGENT_BASE_URL ??
  "/projects/rosetta-log-analyzer/api/agent";
```

### C2. Add imports

Extend the existing type import from `@/types/analysis` with
`AgentAnalysisResult`, and add:

```ts
import { mapAgentAnalysis } from "@/lib/mapAnalysis";
```

### C3. Add `analyzeSingleFile` beside `classifySingleFile` (same style)

```ts
  const analyzeSingleFile = async (file: File): Promise<AgentAnalysisResult> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${AGENT_BASE_URL}/analyze`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        errorText || `Analysis failed with status ${response.status}`
      );
    }

    return (await response.json()) as AgentAnalysisResult;
  };
```

### C4. Replace the `try` block inside `runAnalysisProgress`

Current content (for orientation — classify all, map canned, complete all
steps at once):

```ts
    try {
      setActivityProgress({
        completedStepIds: ["files_uploaded", "reading_logs"],
        activeStepId: "failure_detection",
      });

      const classifyResults = await Promise.all(
        filesToAnalyze.map((file) => classifySingleFile(file))
      );

      const analyses = classifyResults.map(classifyResponseToAnalysis);

      setAnalysisResponse({
        analyses,
        source: "api",
        generatedAt: new Date().toISOString(),
      });

      setActivityProgress({
        completedStepIds: stepOrder,
        activeStepId: undefined,
      });
    } catch (error) {
```

Replace that `try` block body with:

```ts
      setActivityProgress({
        completedStepIds: ["files_uploaded", "reading_logs"],
        activeStepId: "failure_detection",
      });

      const classifyResults = await Promise.all(
        filesToAnalyze.map((file) => classifySingleFile(file))
      );

      setActivityProgress({
        completedStepIds: ["files_uploaded", "reading_logs", "failure_detection"],
        activeStepId: "calling_ai_model",
      });

      const agentResults = await Promise.allSettled(
        filesToAnalyze.map((file) => analyzeSingleFile(file))
      );

      const analyses = filesToAnalyze.map((file, index) => {
        const agentResult = agentResults[index];
        if (agentResult.status === "fulfilled") {
          return mapAgentAnalysis(
            agentResult.value,
            file.name,
            classifyResults[index].status
          );
        }
        return classifyResponseToAnalysis(classifyResults[index]);
      });

      const failedCount = agentResults.filter(
        (result) => result.status === "rejected"
      ).length;
      if (failedCount > 0) {
        setAnalysisError(
          failedCount === filesToAnalyze.length
            ? "AI analysis unavailable — showing parser-only results. Is the agent running on port 8001?"
            : `AI analysis failed for ${failedCount} file(s) — parser-only results shown for those.`
        );
      }

      setAnalysisResponse({
        analyses,
        source: "api",
        generatedAt: new Date().toISOString(),
      });

      setActivityProgress({
        completedStepIds: stepOrder,
        activeStepId: undefined,
      });
```

Keep the existing `catch`/`finally` unchanged (classifier failure remains a
hard error — the pipeline needs Reed's service up).

Note the activity feed is now honest: "Failure Detection Complete" flips when
the classifier really answered, "Calling AI Model" is genuinely in-flight
during the agent round-trip (GPT-5.4 can take tens of seconds — the step
spinner is the feedback), "Analysis Complete" flips only once results are in
state. Keep `classifyResponseToAnalysis` — it is the fallback path.

### C5. Verify

- `cd client && npx tsc --noEmit` exits 0.
- Rebuild/restart (`./scripts/boot.sh --skip-install`), then in the browser
  through the pod proxy: upload `agent/samples/db_pool_exhaustion.log`, press
  Explain Issue → SeverityCard shows the parser chip AND the cards fill with
  the agent's analysis (with real LLM creds: model-written root cause; with
  none/mock: "Database connection pool exhaustion").
- Paste the built-in demo text but EDIT ONE CHARACTER first (so
  `isDemoScenario` turns off and the real pipeline runs) → cards fill with a
  retry-storm/dependency analysis.
- Upload `agent/samples/healthy_run.log` → "No issues found — this log looks
  healthy.", severity Low.
- Stop the agent (`kill` the 8001 process), analyze again → parser-only
  results plus the banner; UI does not crash. Restart the agent afterwards.

## Phase D — presentation polish (additive)

The agent returns the project's differentiators — cited evidence and
calibrated confidence. Surface them:

1. New `client/components/EvidenceCard.tsx`:

```tsx
"use client";

import type { EvidenceItem } from "@/types/analysis";

interface EvidenceCardProps {
  evidence: EvidenceItem[];
}

export function EvidenceCard({ evidence }: EvidenceCardProps) {
  if (evidence.length === 0) return null;

  return (
    <section className="ubs-card p-5 md:col-span-2 dark:border-[#7A7870]">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-zinc-700 dark:text-zinc-200">
        Evidence
      </h3>
      <ul className="space-y-2">
        {evidence.map((item) => (
          <li
            key={item.lineNumber}
            className="rounded-md border border-black/10 bg-black/[0.03] p-3 dark:border-[#7A7870] dark:bg-black/15"
          >
            <div className="flex items-start gap-3 overflow-x-auto">
              <span className="shrink-0 rounded bg-[#E60000]/10 px-1.5 py-0.5 font-mono text-xs font-semibold text-[#BD000C] dark:bg-[#E60000]/20 dark:text-[#FF9C9C]">
                L{item.lineNumber}
              </span>
              <code className="font-mono text-xs text-zinc-800 dark:text-zinc-100">
                {item.rawText}
              </code>
            </div>
            <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
              {item.whyRelevant}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

   Export it from `client/components/index.ts` alongside the others.

2. `SeverityCard.tsx`: add an optional `confidence?: number` prop; when
   defined render a small muted badge next to the existing severity pill:
   `confidence {Math.round(confidence * 100)}%` — match the card's existing
   text styles. Pass `confidence={activeAnalysis.confidence}` from `page.tsx`.
3. `SummaryCard.tsx`: add an optional `stats?: AnalysisStats` prop; when
   defined render three small chips under the summary text —
   `{totalLines} lines`, `{errorLines} errors` (red tint), `{warningLines}
   warnings` (amber tint) — with dark variants. Pass
   `stats={activeAnalysis.stats}` from `page.tsx`.
4. `page.tsx`: inside the results grid, after `RecommendationCard`, render:

```tsx
                  {activeAnalysis.evidence?.length ? (
                    <EvidenceCard evidence={activeAnalysis.evidence} />
                  ) : null}
```

5. Optional, if time allows: an "Other findings" strip under the grid when
   `activeAnalysis.otherIncidents?.length` — severity-colored dot + title +
   one-line explanation per item, same `ubs-card` chrome.

**Verify:** `npx tsc --noEmit` passes; browser re-check of Phase C5's first
scenario now shows evidence lines whose numbers match the uploaded file
(L14 is a HikariPool error in the sample), the confidence badge, and the
stats chips; toggle dark mode and confirm the new elements render correctly
in both themes.

## Phase E — final checklist

```bash
cd client && npx tsc --noEmit
npm run build -- --webpack
cd .. && ./scripts/boot.sh --skip-install
curl -s http://localhost:8001/health
curl -s -F "file=@agent/samples/db_pool_exhaustion.log" \
  "http://localhost:3000/projects/rosetta-log-analyzer/api/agent/analyze?mock=true" | head -c 300
```

Commit on `llm-implementaion`:
`feat(client): wire UI to analysis agent (rewrite proxy, classify+analyze merge, evidence display)`
— split into two commits if Phase D was done (wiring vs polish). Do not push.
