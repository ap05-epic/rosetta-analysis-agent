# Skill: Output Format

Purpose: the final message must be machine-parseable on the first try. The UI
renders it directly; a malformed answer is a failed analysis regardless of how
good the investigation was.

## Rules

- The final message is EXACTLY one JSON object. No markdown fences, no
  leading prose, no trailing commentary.
- Shape (fields you must produce — ids and stats are filled in by the
  runtime, do not fabricate them):

```json
{
  "overall_status": "critical | degraded | healthy | inconclusive",
  "incidents": [
    {
      "title": "Short, specific, names the root cause",
      "severity": "critical | high | medium | low",
      "confidence": 0.0,
      "human_explanation": "2-4 plain-English sentences.",
      "possible_solutions": ["1 to 3 imperative actions"],
      "evidence": [
        {"line_number": 0, "why_relevant": "why this line backs the claim"}
      ],
      "affected_sources": ["service names from the logs"],
      "first_seen": "timestamp from the logs or null",
      "last_seen": "timestamp from the logs or null"
    }
  ]
}
```

- 0–3 incidents, most severe first. Healthy runs have an empty `incidents`
  array — never a "no problems found" pseudo-incident.
- `evidence[].line_number` must be a line number you saw in a tool result this
  session. The runtime cross-checks them against the input and drops fakes;
  an incident stripped of all its evidence is a bug in YOUR reasoning.
- `first_seen`/`last_seen` come from tool results; use null when the log has
  no timestamps. Never invent times.
- Strings only in `possible_solutions`; each under 200 characters.
- If asked to retry because validation failed, fix ONLY the reported schema
  problem; do not redo the investigation or change your conclusions.
