# Demo logs

```bash
python3 sample-logs/generate_bank_demo_logs.py   # the 5-log demo set  -> sample-logs/demo/
python3 sample-logs/generate_category_logs.py    # 12-log classifier sweep (testing)
python3 sample-logs/generate_demo_logs.py        # 5 earlier narrative scenarios
python3 sample-logs/verify_category_logs.py      # asserts every category lands where intended
```

Everything is generated and deterministic — same bytes on every run. Ground
truth lives in the generator docstrings. **Never hand-edit a `.log`**; the next
regeneration discards it.

---

## The demo set — `sample-logs/demo/`

Five banking failure modes. Run them in order and the severity badge steps
down on screen while the categories and formats stay varied.

| # | File | Parser verdict | Severity | What it proves |
|---|---|---|---|---|
| 1 | `01-payments-settlement-outage.log` | DB_CONNECTION_ERROR | **CRITICAL** | separates cause from cascade |
| 2 | `02-regulatory-report-schema-drift.log` | SQL_SCHEMA_ERROR | **HIGH** | names the exact column and release |
| 3 | `03-trade-capture-gateway.log` | UNKNOWN | **CRITICAL** | regex can't classify it at all |
| 4 | `04-entitlement-rotation-blocked.log` | PERMISSION_ERROR | **MEDIUM** | one grant, no data change |
| 5 | `05-internal-dashboard-timeout.log` | TIMEOUT | **LOW** | FAIL, but it can wait |

**1 — Payments settlement outage** (344 lines). A regulatory extract quietly
opens 40 reader sessions; twenty lines later the pool is full and three payment
streams miss the 22:00 cut-off. The cause and the symptoms sit far apart in the
file, and the failing thing is not the thing that caused it.

**2 — Regulatory report schema drift** (345 lines). Release 2026.31 renamed
`counterparty_lei` to `lei_code`. Six MiFIR models fail and the submission
deadline is hours away. Watch it name the column, the replacement, and the
release.

**3 — Trade capture gateway** (491 lines). A proprietary pipe-delimited format
with `SEV=E` severity codes and hex return codes — no Airflow markers, no SQL,
nothing the regex recognises. The parser returns `UNKNOWN`; the agent still
finds the venue tag change that started it. **This is the strongest contrast
slide in the deck.**

**4 — Entitlement rotation blocked** (296 lines). A quarterly review revoked a
grant a feed still needs. Real failure, contained impact, documented fallback —
the fix is one `GRANT`.

**5 — Internal dashboard timeout** (259 lines). A cache warm job blows its
deadline. The parser can only say FAIL. Deciding this one waits until morning —
internal only, cached data still serving, hourly retry — is judgement the regex
cannot make.

### A note on severity in mock mode

`--mock` scales severity by the *share* of lines failing plus the presence of a
fatal line. That reproduces the spread above, but it is counting, not reasoning.
Recognising that log 5 is contained *because a fallback exists and nothing
downstream depends on it* requires reading lines that aren't errors — which is
what the model adds over pattern matching. Demo live where you can.

---

## Classifier coverage set — `cat-*.log`

Twelve logs, one per branch of `classifier/regex.py` (nine `ErrorCategory`
values plus `FAILURE_GENERIC`, `UNKNOWN` and `PASS`), 315–466 lines each.
Built for testing, not for the stage.

`verify_category_logs.py` replicates the classifier exactly and asserts all
twelve land in the intended bucket. The classifier returns the **first**
matching category scanning the whole file, so each scenario has to avoid every
pattern belonging to an earlier one — which is why the timeout log never says
"could not connect", and the return-code log never contains the word "timeout".

## Narrative scenarios

| File | Lines | Root cause |
|---|---:|---|
| `nightly-etl-pool-exhaustion.log` | 496 | one analytics query holds 40 connections; three unrelated DAGs starve |
| `payments-deploy-regression.log` | 369 | deploy v4.7.2 introduces a null `PromotionRule` crash |
| `warehouse-schema-drift.log` | 186 | migration 0042 half-applied after a lock timeout |
| `platform-disk-cascade.log` | 277 | WAL archiving fails → disk fills → database PANIC → 503s |
| `healthy-nightly-close.log` | 201 | nothing wrong — proves no false positives |

`platform-disk-cascade.log` is the hardest of these: the true cause is a quiet
`WARNING: archive_command failed` on **line 55**, 94 lines before the first
error and in a different format from everything around it.
