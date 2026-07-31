# Demo logs

Two generated sets. Both are deterministic — same bytes on every run — and both
have documented ground truth so a demo can prove the analysis is correct rather
than just plausible.

```bash
python3 sample-logs/generate_demo_logs.py       # 5 narrative scenarios
python3 sample-logs/generate_category_logs.py   # 12-log classifier sweep
python3 sample-logs/verify_category_logs.py     # asserts every category lands
```

## Set A — classifier coverage (`cat-*.log`)

One log per branch of `classifier/regex.py`, at varying incident severity.
`verify_category_logs.py` replicates the classifier exactly and asserts each
file lands where its name claims.

| File | Lines | Parser verdict | Agent severity | Root cause |
|---|---:|---|---|---|
| `cat-01-sql-schema-error.log` | 343 | FAIL · SQL_SCHEMA_ERROR | critical | migration renamed a column; 5 marts still select the old name |
| `cat-02-sql-syntax-error.log` | 336 | FAIL · SQL_SYNTAX_ERROR | high | template emits a trailing comma before `FROM` |
| `cat-03-sql-type-mismatch.log` | 318 | FAIL · SQL_TYPE_MISMATCH | high | upstream changed `account_id` int → varchar; join breaks |
| `cat-04-db-resource-exhaustion.log` | 363 | FAIL · DB_RESOURCE_EXHAUSTION | high | runaway aggregation OOM-kills postgres |
| `cat-05-db-connection-error.log` | 395 | FAIL · DB_CONNECTION_ERROR | critical | a report hoards the pool; three close jobs starve |
| `cat-06-permission-error.log` | 326 | FAIL · PERMISSION_ERROR | high | credential rotation reached 2 of 6 consumers |
| `cat-07-module-import-error.log` | 315 | FAIL · MODULE_IMPORT_ERROR | high | dependency added to requirements but not to the image |
| `cat-08-timeout.log` | 351 | FAIL · TIMEOUT | high | upstream pricing API blows the 30s deadline |
| `cat-09-return-code-failure.log` | 323 | FAIL · RETURN_CODE_FAILURE | high | verification script exits 2 on a checksum mismatch |
| `cat-10-failure-generic.log` | 343 | FAIL · FAILURE_GENERIC | high | `ValueError`: 11 of 12 partitions — no machine-readable category |
| `cat-11-unknown-format.log` | 465 | FAIL · UNKNOWN | high | bespoke matching-engine format; regex can say nothing |
| `cat-12-healthy-pass.log` | 466 | PASS | healthy | clean run, benign warnings only |

The last two are the interesting demo pair. On `cat-10` the parser can only say
"something failed"; on `cat-11` it cannot even say that — yet the agent explains
both. That contrast is the product argument in two files.

### Why the scenarios read the way they do

The classifier returns the **first** matching category in `CATEGORY_PATTERNS`
order, scanning the whole file. So each scenario has to avoid every pattern
belonging to an earlier category — which is why the timeout log never says
"could not connect", and the return-code log never contains the word "timeout".
Edit these files and re-run `verify_category_logs.py`; it fails loudly if a
stray word moves a log into the wrong bucket.

## Set B — narrative scenarios

Longer incidents where the root cause is deliberately buried under unrelated
errors, for showing the agent doing real work.

| File | Lines | Root cause |
|---|---:|---|
| `nightly-etl-pool-exhaustion.log` | 496 | one analytics query holds 40 connections; three unrelated DAGs starve |
| `payments-deploy-regression.log` | 369 | deploy v4.7.2 introduces a null `PromotionRule` crash |
| `warehouse-schema-drift.log` | 186 | migration 0042 half-applied after a lock timeout |
| `platform-disk-cascade.log` | 277 | WAL archiving fails → disk fills → database PANIC → 503s |
| `healthy-nightly-close.log` | 201 | nothing wrong — proves no false positives |

`platform-disk-cascade.log` is the hardest: the true cause is a quiet
`WARNING: archive_command failed` on **line 55**, 94 lines before the first
error and in a different log format from everything around it.

## Ground truth is in the generators

Each scenario function carries a docstring naming its planted root cause, and
`SCENARIOS` at the bottom of each generator lists the expected classifier
verdict. To tune a scenario, edit the generator and re-run it — never hand-edit
a `.log`, or the next regeneration silently discards your change.
