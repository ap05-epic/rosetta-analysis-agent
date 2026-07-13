# Skill: Root Cause Analysis

Purpose: separate the first domino from the ones it knocked over.

## Procedure

1. **Establish the timeline.** From `get_source_stats` and the error groups'
   `first_seen`, order failures by first occurrence. The earliest failing
   source is the prime suspect; later failures are candidate victims.
2. **Look immediately BEFORE the first failure.** `get_context_window` around
   the earliest error's line number. The trigger often sits in the preceding
   lines: a deploy marker, a config reload, a spike in traffic, a resource
   warning (pool near limit, memory high, disk filling).
3. **Test the causal link.** Use `search_logs` for the mechanism you suspect:
   the pool name, the exception class, the release version, the hostname.
   A causal chain needs a mechanism, not just an order of events.
4. **Try to refute yourself once.** Ask: what would I expect to see if my
   hypothesis were wrong? Search for that. If a "victim" service was already
   erroring before the suspected cause, your chain is broken — rebuild it.

## Common cascade signatures

- **Resource exhaustion**: warnings about a limit (pool/memory/disk/file
  descriptors) → timeouts in the same service → 5xx/timeouts in its callers.
  Root cause is the exhausted resource, not the callers.
- **Bad deploy**: deploy/release/version marker → new exception class or 500
  spike within minutes, often on one service only. Root cause is the release.
- **Dependency outage**: connection refused/reset to one host from many
  services at once. Root cause is the dependency, not the many callers.

## Rules

- One root cause → one incident. Fold the cascade's symptoms into the
  incident's evidence and `affected_sources` instead of separate incidents.
- If two plausible root causes remain after verification, report the stronger
  one as the incident and name the alternative inside `human_explanation`,
  with confidence lowered accordingly.
- No mechanism found? Report the correlation honestly ("errors in A and B
  started within the same minute; the logs do not show which caused which")
  and mark confidence below 0.5 or the run inconclusive.
