# Skill: Triage

Purpose: decide, in one or two tool calls, whether there is anything to
investigate and where to look first. Triage is cheap; a wrong first impression
is expensive.

## Procedure

1. `get_error_summary` is ALWAYS your first call. Read it fully before any
   other tool.
2. Classify the situation:
   - **No errors, no warnings** → conclude healthy immediately. Do not call
     more tools looking for trouble; absence of evidence here IS evidence of
     health.
   - **Warnings only** → usually `healthy` with a `low`/`medium` incident only
     if a warning group is frequent enough to matter (5+ occurrences or an
     alarming message). Occasional retries and slow-query notices are normal
     operations, not incidents.
   - **One dominant error group** → likely a single root cause. Investigate
     that group's earliest sample line.
   - **Several error groups** → suspect a cascade. Note which group starts
     earliest; that is your prime root-cause candidate.
3. Note the noise floor: repeated INFO chatter, health checks, and access logs
   are context, never incidents.

## Judgment rules

- Volume ≠ severity. Three CRITICAL lines about data corruption outrank fifty
  repeated timeout errors.
- Distinct-looking messages can be one failure: same source + same minute +
  same request path usually means one story.
- Set `overall_status` from user impact, not line counts: `critical` = users
  are failing now, `degraded` = errors present but service limping,
  `healthy` = nothing actionable, `inconclusive` = not enough data to tell.
