# Skill: Fix Recommendation

Purpose: turn a diagnosed root cause into 1–3 actions an on-call engineer can
start in the next five minutes.

## Rules

- **Order by leverage**: first the action that stops user impact fastest
  (rollback, restart, failover, raise the exhausted limit), then the fix that
  addresses the cause, then at most one prevention item (alert, test, limit).
- **Be concrete and scoped to the evidence.** Name the service, resource, or
  version from the logs: "Increase the payments-db connection pool
  (HikariCP) above its current cap" — never "optimize database usage."
- **Imperative voice, one action per item.** "Roll back to the previous
  release", not "the team may want to think about rolling back".
- **Only recommend what the evidence supports.** If the logs show pool
  exhaustion but not WHY the pool filled, say "investigate what is holding
  connections (slow queries or leaks)" rather than inventing a specific query
  fix.
- **Respect the blast radius.** Prefer reversible actions (rollback, scale
  up) over destructive ones (dropping data, disabling auth). Never recommend
  deleting anything as a first step.
- For a `healthy` run: no solutions to invent. For `inconclusive`: the
  "solutions" are the data you need next ("enable debug logging on X",
  "re-run with the full log file including timestamps").
