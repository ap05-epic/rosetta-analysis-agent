"""The five-log demo set: banking failure modes, descending severity.

Chosen for what a demo has to prove in two minutes, not for coverage:

  1 critical  a cascade, so the agent must separate cause from symptom
  2 high      a precise fix — it names the column and the release that moved it
  3 high      a bespoke format the regex cannot classify at all (UNKNOWN)
  4 medium    trivially actionable — one grant, no data change
  5 low       calibration: the parser says FAIL, the agent says this can wait

Run in that order and the severity badge steps down on screen while the
categories stay varied. Each log also uses a different format, so the
log-agnostic claim is demonstrated rather than asserted.

Run:  python3 sample-logs/generate_bank_demo_logs.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generate_demo_logs import build  # noqa: E402
from generate_category_logs import noise, tail_fail  # noqa: E402

OUT = Path(__file__).parent / "demo"


def write(name, text, note):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(text, encoding="utf-8")
    print(f"  {name:44s} {text.count(chr(10)):4d} lines   {note}")


# ============================================================ 1 · CRITICAL
def payments_settlement_outage():
    """DB_CONNECTION_ERROR. A regulatory extract hoards the pool and three
    payment batches miss the settlement cut-off. Cause and symptoms are far
    apart in the file — the extract opens its sessions long before anything
    visibly fails."""
    ev = []
    end = noise(ev, 74, start=0, step=12, dag="payments_settlement")

    s = end + 16
    ev.append((s, "{iso} INFO  regreport.runner - trade_repository_extract started "
                  "(scope: EMIR daily, 41.2M rows)"))
    ev.append((s + 3, "{iso} INFO  regreport.runner - trade_repository_extract opened 40 parallel "
                      "reader sessions on core-pay-db"))
    ev.append((s + 40, "{iso} WARN  payments.pool - session pool 42/50 (84%) - above warn threshold 80%"))
    ev.append((s + 74, "{iso} WARN  payments.pool - session pool 49/50 (98%)"))
    ev.append((s + 92, "{iso} WARN  payments.pool - session pool 50/50 (100%) - overflow 7/10 in use"))

    batches = [("EUR_HIGH_VALUE", "batch_4471", 108),
               ("USD_CORRESPONDENT", "batch_4472", 148),
               ("CHF_DOMESTIC", "batch_4473", 191)]
    for name, task, o in batches:
        ev.append((s + o, "{iso} INFO  airflow.task_runner - Running task payments_settlement.%s "
                          "(attempt 1 of 3) stream=%s" % (task, name)))
        ev.append((s + o + 4, "{sys} core-pay-db postgres[%d]: FATAL:  remaining connection slots are "
                              "reserved for non-replication superuser connections" % (6100 + o)))
        ev.append((s + o + 6, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                               "psycopg2.OperationalError: connection to server at \"core-pay-db-01\" "
                               "(10.22.7.4), port 5432 failed: FATAL:  remaining connection slots are "
                               "reserved for non-replication superuser connections",
                               "    at /opt/airflow/dags/payments_settlement/%s.py, line 91, in settle" % task]))
        ev.append((s + o + 9, "{iso} ERROR settlement.engine - stream %s: 0 of %d instructions settled, "
                              "instructions returned to queue" % (name, 1200 + o * 7)))
        ev.append((s + o + 26, "{iso} WARN  airflow.taskinstance - Task %s up for retry: 1 of 3" % task))

    ev.append((s + 236, "{iso} INFO  regreport.runner - trade_repository_extract complete, "
                        "40 sessions released"))
    ev.append((s + 240, "{iso} INFO  payments.pool - session pool 11/50 (22%) - recovered"))
    ev.append((s + 250, "{iso} ERROR settlement.engine - cut-off 22:00 CET passed with 3 streams unsettled"))
    ev.append((s + 258, "{iso} WARN  alerting - SEV-1 declared: value-dated settlement missed for "
                        "3 payment streams"))
    ev.append((s + 266, "{iso} INFO  oncall.bot - paged payments-sre (primary), treasury-duty (secondary)"))
    for i, (_, task, _o) in enumerate(batches):
        tail_fail(ev, s + 280 + i * 4, "payments_settlement", task)
    return build(datetime(2026, 8, 4, 21, 10, 0), ev)


# ============================================================ 2 · HIGH
def regulatory_report_schema_drift():
    """SQL_SCHEMA_ERROR. A release renamed a column in the party dimension and
    every transaction-reporting model that selects it fails, hours before a
    regulatory submission deadline."""
    ev = []
    ev.append((0, "{iso} INFO  release.tracker - release 2026.31 promoted to PROD "
                  "(12 changes, 1 schema change)"))
    ev.append((5, "{sys} reg-db postgres[5501]: LOG:  statement: ALTER TABLE dim_party "
                  "RENAME COLUMN counterparty_lei TO lei_code"))
    ev.append((9, "{iso} INFO  release.tracker - schema change applied; "
                  "no consumer impact assessment attached to the change record"))
    end = noise(ev, 70, start=40, step=13, dag="mifir_reporting")

    models = ["stg_transaction_report", "int_party_enrichment", "fct_transaction_report",
              "mart_mifir_submission", "rpt_daily_control_totals", "rpt_lei_exceptions"]
    s = end + 22
    for i, m in enumerate(models):
        o = s + i * 24
        ev.append((o, "{iso} INFO  dbt.runner - %d of 88 START model reporting.%s" % (52 + i, m)))
        ev.append((o + 3, ["{iso} ERROR dbt.runner - Database Error in model %s "
                           "(models/mifir/%s.sql)" % (m, m),
                           "  column \"counterparty_lei\" does not exist",
                           "  LINE 18:   p.counterparty_lei AS lei,",
                           "                ^",
                           "  HINT:  Perhaps you meant to reference the column \"p.lei_code\"."]))
        ev.append((o + 6, "{sys} reg-db postgres[%d]: ERROR:  column \"counterparty_lei\" does not exist "
                          "at character 389" % (5600 + i)))
        ev.append((o + 8, "{iso} ERROR dbt.adapter - psycopg2.errors.UndefinedColumn: "
                          "column dim_party.counterparty_lei does not exist"))
    e2 = s + len(models) * 24 + 26
    ev.append((e2, "{iso} WARN  dbt.runner - 6 of 88 models FAILED, 82 completed successfully"))
    ev.append((e2 + 6, "{iso} ERROR mifir_reporting - submission file for 2026-08-03 not produced; "
                       "regulatory deadline 07:00 CET"))
    ev.append((e2 + 12, "{iso} WARN  alerting - SEV-2: transaction reporting submission at risk"))
    ev.append((e2 + 18, "{iso} ERROR airflow.taskinstance - Task failed with exception: dbt returned non-zero"))
    tail_fail(ev, e2 + 24, "mifir_reporting", "dbt_run_mifir")
    return build(datetime(2026, 8, 3, 3, 20, 0), ev)


# ============================================================ 3 · HIGH (UNKNOWN)
def trade_capture_gateway():
    """UNKNOWN. A legacy trade-capture gateway in a proprietary pipe-delimited
    format. The regex classifier has no pattern for any of it — the agent has
    to work purely from the content. Deliberately free of every classifier
    token, including the words the other four logs rely on."""
    ev = []
    for i in range(300):
        s = i * 4
        ev.append((s, "20260802|{isoz}|TCG-EDGE|SEQ=%07d|SEV=I|RC=0x1000|"
                      "MSG=trade accepted|VENUE=XSWX|QTY=%d|PX=%d.%02d"
                      % (4400000 + i, 100 + (i * 37) % 900, 90 + i % 40, i % 100)))
        if i % 4 == 1:
            ev.append((s + 1, "20260802|{isoz}|TCG-VAL |SEQ=%07d|SEV=I|RC=0x1010|"
                              "MSG=validation ok|RULESET=v14.2|LATENCY_US=%d"
                              % (4400000 + i, 180 + i % 120)))
        if i % 6 == 2:
            ev.append((s + 2, "20260802|{isoz}|TCG-PERS|SEQ=%07d|SEV=I|RC=0x1020|"
                              "MSG=persisted to book|BOOK=EQ-CASH-CH|DEPTH=%d"
                              % (4400000 + i, 40 + i % 60)))
        if i % 9 == 5:
            ev.append((s + 3, "20260802|{isoz}|TCG-EDGE|SEQ=%07d|SEV=D|RC=0x0002|"
                              "MSG=heartbeat|PEER=VENUE-GW-02|RTT_US=%d" % (4400000 + i, 300 + i % 200)))

    s = 1240
    ev.append((s, "20260802|{isoz}|TCG-VAL |SEQ=4500001|SEV=W|RC=0x2F30|"
                  "MSG=unrecognised tag in inbound message|TAG=5847|RULESET=v14.2|VENUE=XSWX"))
    ev.append((s + 4, "20260802|{isoz}|TCG-VAL |SEQ=4500002|SEV=W|RC=0x2F30|"
                      "MSG=unrecognised tag in inbound message|TAG=5847|RULESET=v14.2|VENUE=XSWX"))
    ev.append((s + 9, "20260802|{isoz}|TCG-VAL |SEQ=4500003|SEV=E|RC=0x4A17|"
                      "MSG=validation rejected, mandatory field absent|TAG=5847|VENUE=XSWX"))
    for i in range(6):
        ev.append((s + 14 + i * 5, "20260802|{isoz}|TCG-VAL |SEQ=%07d|SEV=E|RC=0x4A17|"
                                   "MSG=validation rejected, mandatory field absent|TAG=5847|VENUE=XSWX"
                   % (4500004 + i)))
    ev.append((s + 50, "20260802|{isoz}|TCG-PERS|SEQ=4500020|SEV=W|RC=0x2F41|"
                       "MSG=inbound queue depth rising|DEPTH=8400|HIGH_WATER=9000"))
    ev.append((s + 58, "20260802|{isoz}|TCG-PERS|SEQ=4500021|SEV=E|RC=0x4B02|"
                       "MSG=inbound queue above high water, backpressure applied|DEPTH=9140"))
    ev.append((s + 66, "20260802|{isoz}|TCG-EDGE|SEQ=4500022|SEV=F|RC=0x5001|"
                       "MSG=intake suspended for venue|VENUE=XSWX|UNPROCESSED=9140"))
    ev.append((s + 74, "20260802|{isoz}|TCG-SUPV|SEQ=4500023|SEV=W|RC=0x2F55|"
                       "MSG=venue ruleset v14.2 predates venue notice VN-2026-118 effective 2026-08-02"))
    for i in range(20):
        ev.append((s + 84 + i * 6, "20260802|{isoz}|TCG-SUPV|SEQ=%07d|SEV=W|RC=0x2F60|"
                                   "MSG=awaiting ruleset update|ELAPSED_S=%d"
                   % (4500100 + i, (i + 1) * 30)))
    return build(datetime(2026, 8, 2, 8, 0, 0), ev)


# ============================================================ 4 · MEDIUM
def entitlement_rotation_blocked():
    """PERMISSION_ERROR. A quarterly entitlement review revoked a grant that a
    reference-data feed still needs. One feed blocked, documented fallback in
    place, no client impact — the fix is a single grant. Avoids every
    connection/memory/schema token so the classifier lands on PERMISSION_ERROR."""
    ev = []
    ev.append((0, "{iso} INFO  iam.review - quarterly entitlement review R-2026-Q3 applied "
                  "(214 grants revoked, 38 retained)"))
    ev.append((6, "{iso} WARN  iam.review - svc-refdata lost WRITE on curated.instrument_master "
                  "(no owner sign-off recorded against the retain list)"))
    end = noise(ev, 66, start=40, step=13, dag="reference_data_load")

    s = end + 20
    for i, attempt in enumerate((1, 2, 3)):
        o = s + i * 44
        ev.append((o, "{iso} INFO  airflow.task_runner - Running task reference_data_load.write_master "
                      "(attempt %d of 3)" % attempt))
        ev.append((o + 5, "{sys} refdata-db postgres[3308]: ERROR:  permission denied for table "
                          "curated.instrument_master"))
        ev.append((o + 7, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                           "psycopg2.errors.InsufficientPrivilege: permission denied for table "
                           "curated.instrument_master",
                           "    at /opt/airflow/dags/reference_data_load/write_master.py, line 64, in execute"]))
        if attempt < 3:
            ev.append((o + 10, "{iso} WARN  airflow.taskinstance - Task up for retry: %d of 3" % attempt))

    ev.append((s + 140, "{iso} ERROR objectstore.client - PUT s3://refdata-curated/instruments/"
                        "2026-08-01/part-0001.parquet returned 403 Forbidden"))
    ev.append((s + 150, "{iso} INFO  reference_data_load - fallback engaged: consumers served from "
                        "yesterday's instrument_master snapshot (documented in RUN-441)"))
    ev.append((s + 158, "{iso} INFO  reference_data_load - 0 new instruments today; "
                        "no downstream job depends on same-day freshness"))
    ev.append((s + 170, "{iso} INFO  oncall.bot - raised INC-88214 to data-governance, priority P3"))
    tail_fail(ev, s + 182, "reference_data_load", "write_master")
    return build(datetime(2026, 8, 1, 4, 30, 0), ev)


# ============================================================ 5 · LOW
def internal_dashboard_timeout():
    """TIMEOUT, but low impact — an internal cache warm job for a risk dashboard.
    The dashboard keeps serving cached figures, nothing client-facing depends on
    it, and the next scheduled run is an hour away. The parser can only say
    FAIL; the judgement that this is not worth a page is the agent's."""
    ev = []
    end = noise(ev, 60, start=0, step=13, dag="risk_dashboard_cache")
    s = end + 18
    ev.append((s, "{iso} INFO  airflow.task_runner - Running task risk_dashboard_cache.warm_var_grid "
                  "(attempt 1 of 3)"))
    ev.append((s + 4, "{iso} INFO  dashboard.cache - warming VaR grid for 14 desks "
                      "(previous warm completed 09:00, hit ratio since: 0.94)"))
    ev.append((s + 30, "{iso} WARN  dashboard.cache - grid build slower than usual: "
                       "6 of 14 desks after 20 minutes"))
    ev.append((s + 52, "{iso} ERROR dashboard.cache - grid build request timed out after 1800000ms; "
                       "8 of 14 desks not refreshed"))
    ev.append((s + 56, "{iso} ERROR airflow.taskinstance - Task failed with exception: "
                       "TimeoutError: deadline exceeded after 1800.0s"))
    ev.append((s + 66, "{iso} INFO  dashboard.cache - serving cached grid from 09:00 warm; "
                       "dashboard remains available to all users"))
    ev.append((s + 72, "{iso} INFO  risk_dashboard_cache - internal dashboard only; "
                       "no client-facing or regulatory consumer of this cache"))
    ev.append((s + 78, "{iso} INFO  airflow.scheduler - next scheduled run of risk_dashboard_cache "
                       "at 11:00 (hourly); no downstream tasks depend on this one"))
    tail_fail(ev, s + 90, "risk_dashboard_cache", "warm_var_grid")
    return build(datetime(2026, 7, 31, 10, 0, 0), ev)


SCENARIOS = [
    ("01-payments-settlement-outage.log", payments_settlement_outage,
     "CRITICAL · DB_CONNECTION_ERROR · cause vs cascade"),
    ("02-regulatory-report-schema-drift.log", regulatory_report_schema_drift,
     "HIGH     · SQL_SCHEMA_ERROR    · names the exact column"),
    ("03-trade-capture-gateway.log", trade_capture_gateway,
     "HIGH     · UNKNOWN             · regex can't classify it at all"),
    ("04-entitlement-rotation-blocked.log", entitlement_rotation_blocked,
     "MEDIUM   · PERMISSION_ERROR    · one grant, no data change"),
    ("05-internal-dashboard-timeout.log", internal_dashboard_timeout,
     "LOW      · TIMEOUT             · FAIL, but it can wait"),
]

if __name__ == "__main__":
    print("Generating the bank demo set into", OUT)
    for name, fn, note in SCENARIOS:
        write(name, fn(), note)
