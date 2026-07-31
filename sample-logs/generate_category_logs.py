"""Generate a log per regex-classifier category, at varying incident severity.

Twelve files that between them hit every branch of classifier/regex.py:
the nine ErrorCategory patterns, FAILURE_GENERIC, UNKNOWN, and PASS.

The classifier returns the FIRST matching category in CATEGORY_PATTERNS order,
scanning the WHOLE file — so each scenario must avoid every pattern belonging
to an earlier category. That constraint is why, for example, the timeout log
never says "could not connect" and the return-code log never says "timeout".
`verify_category_logs.py` asserts the result, so a careless edit fails loudly.

Run:  python3 sample-logs/generate_category_logs.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generate_demo_logs import build, write  # noqa: E402  (shared helpers)

OUT = Path(__file__).parent


# ---------------------------------------------------------------- noise floor
# Deliberately free of every CATEGORY_PATTERNS token, so background chatter
# can never decide a file's category.

_TASKS = ["extract_source", "validate_batch", "build_staging", "load_dimension",
          "refresh_marts", "publish_metrics", "archive_outputs", "notify_owners"]


def noise(ev, count, start=0, step=13, dag="daily_pipeline", success=True):
    """Append `count` rounds of category-safe routine chatter."""
    for i in range(count):
        s = start + i * step
        task = _TASKS[i % len(_TASKS)]
        ev.append((s, "{iso} INFO  airflow.scheduler - Heartbeat: %d running, %d queued, %d success today"
                   % (3 - i % 3, i % 4, 60 + i)))
        if i % 2 == 0:
            ev.append((s + 2, "{iso} INFO  airflow.task_runner - Running task %s.%s (attempt 1 of 3)"
                       % (dag, task)))
            ev.append((s + 6, "{iso} INFO  %s.%s - processed %d rows in %d.%01ds"
                       % (dag, task, 1400 + i * 617, 4 + i % 11, i % 10)))
            if success:
                ev.append((s + 9, "{iso} INFO  airflow.taskinstance - Marking task as SUCCESS. "
                                  "dag_id=%s, task_id=%s" % (dag, task)))
                ev.append((s + 9, "{iso} INFO  airflow.local_task_job - Task exited with return code 0"))
        if i % 3 == 0:
            ev.append((s + 4, "{sys} etl-node-01 postgres[%d]: LOG:  checkpoint complete: wrote %d buffers"
                       % (3100 + i, 700 + i * 53)))
        if i % 4 == 1:
            ev.append((s + 7, "{iso} DEBUG airflow.executor - Sent task instance to CeleryExecutor queue=default"))
        if i % 5 == 2:
            ev.append((s + 8, "{iso} INFO  airflow.metrics - emitted %d statsd gauges to metrics-relay:8125"
                       % (30 + i % 15)))
        if i % 6 == 4:
            ev.append((s + 5, "{iso} DEBUG airflow.dagrun - DagRun state refreshed, 0 tasks deferred"))
        if i % 7 == 3:
            ev.append((s + 3, "{iso} INFO  audit.trail - user=svc-etl action=read resource=%s result=allow" % task))
    return start + count * step


def tail_fail(ev, s, dag, task, marker=True, rc=1):
    """Standard Airflow failure tail. rc=None omits the return-code line."""
    if marker:
        ev.append((s, "{iso} ERROR airflow.taskinstance - Marking task as FAILED. "
                      "dag_id=%s, task_id=%s" % (dag, task)))
    if rc is not None:
        ev.append((s + 1, "{iso} INFO  airflow.local_task_job - Task exited with return code %d" % rc))
    ev.append((s + 2, "{iso} ERROR airflow.dagrun - DagRun %s finished with failed tasks" % dag))


# ============================================================ 01 SQL_SCHEMA
def sql_schema_error():
    """A migration renamed a column; every mart selecting the old name dies."""
    ev = []
    ev.append((0, "{iso} INFO  migrate.runner - Applying migration 0117_rename_customer_tier"))
    ev.append((4, "{sys} warehouse-db postgres[7301]: LOG:  statement: ALTER TABLE dim_customer "
                  "RENAME COLUMN customer_tier TO tier_code"))
    ev.append((9, "{iso} INFO  migrate.runner - Migration 0117 applied (1 of 2 statements)"))
    ev.append((12, "{iso} WARN  migrate.runner - Statement 2 of 2 skipped: dependent view refresh "
                   "was not scheduled in this release"))
    end = noise(ev, 72, start=40, step=14, dag="warehouse_build")

    models = ["mart_customer_value", "mart_tier_migration", "mart_retention",
              "rpt_exec_summary", "rpt_segment_mix"]
    s = end + 20
    for i, m in enumerate(models):
        o = s + i * 26
        ev.append((o, "{iso} INFO  dbt.runner - %d of 71 START model warehouse.%s" % (48 + i, m)))
        ev.append((o + 3, ["{iso} ERROR dbt.runner - Database Error in model %s (models/marts/%s.sql)" % (m, m),
                           "  column \"customer_tier\" does not exist",
                           "  LINE 22:   d.customer_tier AS tier,",
                           "                ^",
                           "  HINT:  Perhaps you meant to reference the column \"d.tier_code\"."]))
        ev.append((o + 6, "{sys} warehouse-db postgres[%d]: ERROR:  column \"customer_tier\" does not exist "
                          "at character 412" % (7400 + i)))
        ev.append((o + 8, "{iso} ERROR dbt.adapter - psycopg2.errors.UndefinedColumn: "
                          "column dim_customer.customer_tier does not exist"))
    end2 = s + len(models) * 26 + 30
    ev.append((end2, "{iso} WARN  dbt.runner - 5 of 71 models FAILED, 66 completed successfully"))
    ev.append((end2 + 4, "{iso} ERROR airflow.taskinstance - Task failed with exception: dbt returned non-zero"))
    tail_fail(ev, end2 + 8, "warehouse_build", "dbt_run_marts")
    return build(datetime(2026, 8, 3, 4, 15, 0), ev)


# ============================================================ 02 SQL_SYNTAX
def sql_syntax_error():
    """A templated SQL builder emits a trailing comma before FROM."""
    ev = []
    end = noise(ev, 78, start=0, step=12, dag="revenue_rollup")
    ev.append((end + 15, "{iso} INFO  sqlbuilder - rendering template margin_by_desk.sql.j2 "
                         "(14 dimensions, 3 optional blocks)"))
    ev.append((end + 18, "{iso} DEBUG sqlbuilder - optional block 'desk_region' enabled; "
                         "trailing separator not stripped"))
    s = end + 26
    ev.append((s, "{iso} INFO  airflow.task_runner - Running task revenue_rollup.compute_margin_bands (attempt 1 of 3)"))
    ev.append((s + 4, ["{sys} revenue-db postgres[8801]: ERROR:  syntax error at or near \"FROM\"",
                       "{sys} revenue-db postgres[8801]: STATEMENT:  SELECT d.desk_id, d.desk_name, "
                       "SUM(t.notional) AS notional, d.desk_region, FROM trades t JOIN desks d USING (desk_id)"]))
    ev.append((s + 7, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                       "psycopg2.errors.SyntaxError: syntax error at or near \"FROM\"",
                       "LINE 4:   d.desk_region, FROM trades t",
                       "                         ^",
                       "    at /opt/airflow/dags/revenue_rollup/compute_margin_bands.py, line 61, in execute"]))
    for i, r in enumerate((2, 3)):
        ev.append((s + 40 + i * 45, "{iso} ERROR airflow.taskinstance - Task failed with exception "
                                    "(attempt %d of 3): same rendered statement" % r))
    ev.append((s + 140, "{iso} WARN  airflow.scheduler - 5 downstream tasks in revenue_rollup will not be scheduled"))
    tail_fail(ev, s + 150, "revenue_rollup", "compute_margin_bands")
    return build(datetime(2026, 8, 2, 6, 30, 0), ev)


# ============================================================ 03 SQL_TYPE
def sql_type_mismatch():
    """Upstream changed account_id from integer to varchar; a join stops working."""
    ev = []
    ev.append((0, "{iso} INFO  contract.watcher - upstream schema version for feed 'accounts' "
                  "moved 4.2.0 -> 4.3.0"))
    ev.append((3, "{iso} WARN  contract.watcher - field accounts.account_id changed physical type "
                  "integer -> character varying (no consumer sign-off recorded)"))
    end = noise(ev, 74, start=30, step=13, dag="positions_build")
    s = end + 24
    ev.append((s, "{iso} INFO  airflow.task_runner - Running task positions_build.join_accounts (attempt 1 of 3)"))
    ev.append((s + 5, ["{sys} risk-db postgres[6210]: ERROR:  operator does not exist: "
                       "character varying = integer",
                       "{sys} risk-db postgres[6210]: HINT:  No operator matches the given name and "
                       "argument types. You might need to add explicit type casts."]))
    ev.append((s + 8, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                       "psycopg2.errors.UndefinedFunction: operator does not exist: "
                       "character varying = integer",
                       "    at /opt/airflow/dags/positions_build/join_accounts.py, line 44, in execute",
                       "    ON p.account_id = a.account_id"]))
    ev.append((s + 30, "{iso} INFO  positions_build.join_accounts - 0 of 41,882 rows joined; "
                       "falling back to previous snapshot"))
    ev.append((s + 60, "{iso} WARN  positions_build - snapshot is 1 day stale; "
                       "downstream risk metrics flagged as non-current"))
    tail_fail(ev, s + 90, "positions_build", "join_accounts")
    return build(datetime(2026, 8, 1, 5, 45, 0), ev)


# ============================================================ 04 DB_RESOURCE
def db_resource_exhaustion():
    """A runaway aggregation exhausts the box; postgres is killed and restarts."""
    ev = []
    end = noise(ev, 84, start=0, step=11, dag="analytics_refresh")
    s = end + 18
    ev.append((s, "{iso} INFO  airflow.task_runner - Running task analytics_refresh.rebuild_cube (attempt 1 of 3)"))
    ev.append((s + 4, "{sys} analytics-db postgres[9110]: LOG:  statement: SET work_mem='8GB'; "
                      "INSERT INTO cube.fact_wide SELECT * FROM staging.events_exploded"))
    ev.append((s + 30, "{iso} WARN  resourcemon - analytics-db-01 high VMem usage 84% (53.8G of 64.0G)"))
    ev.append((s + 55, "{iso} WARN  resourcemon - analytics-db-01 high VMem usage 93% (59.5G of 64.0G)"))
    ev.append((s + 74, "{iso} WARN  resourcemon - analytics-db-01 high VMem usage 99% (63.4G of 64.0G) "
                       "- CRITICAL threshold breached"))
    ev.append((s + 82, "{sys} analytics-db kernel: Out of memory: Killed process 9110 (postgres) "
                       "total-vm:61403112kB anon-rss:59211004kB"))
    ev.append((s + 84, "{sys} analytics-db postgres[1]: LOG:  server process (PID 9110) was terminated "
                       "by signal 9: Killed"))
    ev.append((s + 86, "{sys} analytics-db postgres[1]: LOG:  terminating any other active server processes"))
    ev.append((s + 90, "{sys} analytics-db postgres[1]: LOG:  database system is in recovery mode"))
    for i, o in enumerate((100, 118, 137, 158)):
        ev.append((s + o, "{iso} ERROR reporting.api - dashboard query rejected: backend unavailable "
                          "during recovery (request %d)" % (5510 + i)))
    ev.append((s + 172, "{iso} WARN  alerting - SEV-2 declared: analytics read path unavailable, "
                        "4 dashboards affected"))
    ev.append((s + 205, "{sys} analytics-db postgres[1]: LOG:  database system is ready to accept connections"))
    ev.append((s + 215, "{iso} ERROR airflow.taskinstance - Task failed with exception: backend "
                        "restarted mid-statement"))
    tail_fail(ev, s + 220, "analytics_refresh", "rebuild_cube")
    return build(datetime(2026, 7, 31, 2, 5, 0), ev)


# ============================================================ 05 DB_CONNECTION
def db_connection_error():
    """A long report hoards the pool; unrelated jobs starve. No memory wording."""
    ev = []
    end = noise(ev, 88, start=0, step=12, dag="nightly_close")
    s = end + 20
    ev.append((s, "{iso} INFO  reporting.runner - regulatory_extract opened 44 parallel reader sessions"))
    ev.append((s + 20, "{iso} WARN  airflow.utils.db - pool usage 41/50 (82%) - above warn threshold 80%"))
    ev.append((s + 44, "{iso} WARN  airflow.utils.db - pool usage 49/50 (98%)"))
    ev.append((s + 58, "{iso} WARN  airflow.utils.db - pool usage 50/50 (100%) - overflow 6/10 in use"))
    victims = [("ledger_sync", "post_entries", 70), ("fx_revalue", "apply_rates", 104),
               ("cash_match", "reconcile", 141)]
    for dag, task, o in victims:
        ev.append((s + o, "{iso} INFO  airflow.task_runner - Running task %s.%s (attempt 1 of 3)" % (dag, task)))
        ev.append((s + o + 4, "{sys} core-db postgres[%d]: FATAL:  remaining connection slots are reserved "
                              "for non-replication superuser connections" % (5200 + o)))
        ev.append((s + o + 6, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                               "psycopg2.OperationalError: connection to server at \"core-db-01\" "
                               "(10.40.3.12), port 5432 failed: FATAL:  remaining connection slots "
                               "are reserved for non-replication superuser connections",
                               "    at /opt/airflow/dags/%s/%s.py, line 73, in execute" % (dag, task)]))
        ev.append((s + o + 26, "{iso} WARN  airflow.taskinstance - Task %s.%s up for retry: 1 of 3" % (dag, task)))
    ev.append((s + 190, "{iso} INFO  reporting.runner - regulatory_extract finished, sessions released"))
    ev.append((s + 194, "{iso} INFO  airflow.utils.db - pool usage 9/50 (18%) - recovered"))
    ev.append((s + 210, "{iso} WARN  alerting - SEV-2: three close jobs failed inside the settlement window"))
    for i, (dag, task, _) in enumerate(victims):
        tail_fail(ev, s + 230 + i * 4, dag, task)
    return build(datetime(2026, 7, 30, 1, 20, 0), ev)


# ============================================================ 06 PERMISSION
def permission_error():
    """Credential rotation didn't reach the workers. No connection/memory wording."""
    ev = []
    ev.append((0, "{iso} INFO  iam.rotator - rotated secret svc-etl/warehouse (version 41 -> 42)"))
    ev.append((6, "{iso} WARN  iam.rotator - 2 of 6 consumers acknowledged the new version"))
    end = noise(ev, 76, start=30, step=12, dag="market_data_load")
    s = end + 22
    ev.append((s, "{iso} INFO  airflow.task_runner - Running task market_data_load.write_curated (attempt 1 of 3)"))
    ev.append((s + 5, "{sys} warehouse-db postgres[4402]: ERROR:  permission denied for table curated.fx_rates"))
    ev.append((s + 7, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                       "psycopg2.errors.InsufficientPrivilege: permission denied for table curated.fx_rates",
                       "    at /opt/airflow/dags/market_data_load/write_curated.py, line 58, in execute"]))
    ev.append((s + 24, "{iso} ERROR objectstore.client - PUT s3://curated-zone/fx/2026-07-29/part-0001.parquet "
                       "returned 403 Forbidden (token version 41)"))
    ev.append((s + 27, "{iso} ERROR objectstore.client - PUT s3://curated-zone/fx/2026-07-29/part-0002.parquet "
                       "returned 403 Forbidden (token version 41)"))
    ev.append((s + 40, "{iso} WARN  market_data_load - 0 of 18 partitions written; curated zone left at "
                       "yesterday's snapshot"))
    ev.append((s + 62, "{iso} ERROR api.gateway - downstream request unauthorized: consumer presented "
                       "secret version 41, expected 42"))
    ev.append((s + 90, "{iso} INFO  oncall.bot - paged data-platform: curated refresh blocked on credentials"))
    tail_fail(ev, s + 110, "market_data_load", "write_curated")
    return build(datetime(2026, 7, 29, 3, 40, 0), ev)


# ============================================================ 07 MODULE_IMPORT
def module_import_error():
    """A release added a dependency that never made it into the worker image."""
    ev = []
    ev.append((0, "{iso} INFO  deploy-agent - Deployment started: airflow-workers v9.3.0 (commit 4c81ab2)"))
    ev.append((22, "{iso} INFO  deploy-agent - Deployment finished: 6/6 workers now on v9.3.0"))
    ev.append((26, "{iso} INFO  health-checker - airflow-workers liveness OK (6/6 ready)"))
    end = noise(ev, 70, start=40, step=12, dag="feature_store")
    s = end + 20
    for i, attempt in enumerate((1, 2, 3)):
        o = s + i * 48
        ev.append((o, "{iso} INFO  airflow.task_runner - Running task feature_store.write_parquet "
                      "(attempt %d of 3)" % attempt))
        ev.append((o + 4, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                           "Traceback (most recent call last):",
                           "  File \"/opt/airflow/dags/feature_store/write_parquet.py\", line 12, in <module>",
                           "    import pyarrow.parquet as pq",
                           "ModuleNotFoundError: No module named 'pyarrow'"]))
        if attempt < 3:
            ev.append((o + 8, "{iso} WARN  airflow.taskinstance - Task up for retry: %d of 3" % attempt))
    ev.append((s + 156, "{iso} INFO  worker.introspect - image airflow-workers:9.3.0 built from "
                        "requirements.lock dated 2026-07-11; pyarrow added to requirements.txt 2026-07-24"))
    ev.append((s + 170, "{iso} WARN  feature_store - 3 downstream feature groups will serve stale values"))
    tail_fail(ev, s + 185, "feature_store", "write_parquet")
    return build(datetime(2026, 7, 28, 7, 10, 0), ev)


# ============================================================ 08 TIMEOUT
def timeout_failure():
    """An upstream pricing API degrades; deadlines are exceeded. No conn wording."""
    ev = []
    end = noise(ev, 80, start=0, step=12, dag="valuation_run")
    s = end + 18
    ev.append((s, "{iso} WARN  pricing.client - upstream p99 latency 8420ms (baseline 240ms)"))
    ev.append((s + 14, "{iso} WARN  pricing.client - upstream p99 latency 19870ms (baseline 240ms)"))
    for i, attempt in enumerate((1, 2, 3)):
        o = s + 26 + i * 52
        ev.append((o, "{iso} INFO  airflow.task_runner - Running task valuation_run.fetch_curves "
                      "(attempt %d of 3)" % attempt))
        ev.append((o + 6, "{iso} ERROR pricing.client - GET /v3/curves/eod request timed out after 30000ms"))
        ev.append((o + 8, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                           "grpc.StatusCode.DEADLINE_EXCEEDED: deadline exceeded after 30.0s",
                           "    at /opt/airflow/dags/valuation_run/fetch_curves.py, line 88, in execute"]))
        if attempt < 3:
            ev.append((o + 12, "{iso} WARN  airflow.taskinstance - Task up for retry: %d of 3" % attempt))
    ev.append((s + 190, "{iso} ERROR valuation_run - execution timeout for the 06:00 valuation window; "
                        "0 of 2,140 curves refreshed"))
    ev.append((s + 205, "{iso} WARN  alerting - SEV-3: valuations will be published against "
                        "yesterday's curves unless resolved by 07:30"))
    tail_fail(ev, s + 220, "valuation_run", "fetch_curves")
    return build(datetime(2026, 7, 27, 5, 55, 0), ev)


# ============================================================ 09 RETURN_CODE
def return_code_failure():
    """A shell step exits non-zero and says nothing else machine-readable.
    Contains no timeout/connection/permission/import/SQL wording by design."""
    ev = []
    end = noise(ev, 76, start=0, step=12, dag="file_delivery")
    s = end + 20
    ev.append((s, "{iso} INFO  airflow.task_runner - Running task file_delivery.verify_bundle (attempt 1 of 3)"))
    ev.append((s + 3, "{iso} INFO  bash.operator - running /opt/scripts/verify_bundle.sh --strict"))
    ev.append((s + 8, "{iso} INFO  verify_bundle.sh - 412 files present, 412 expected"))
    ev.append((s + 12, "{iso} ERROR verify_bundle.sh - checksum mismatch on 3 files:"))
    ev.append((s + 13, "{iso} ERROR verify_bundle.sh -   positions_20260726.csv "
                       "(manifest 9f21ac, computed 4b7e10)"))
    ev.append((s + 14, "{iso} ERROR verify_bundle.sh -   trades_20260726.csv "
                       "(manifest 77c0d3, computed b1904e)"))
    ev.append((s + 15, "{iso} ERROR verify_bundle.sh -   fees_20260726.csv "
                       "(manifest 2ad884, computed 5e6612)"))
    ev.append((s + 18, "{iso} ERROR bash.operator - /opt/scripts/verify_bundle.sh finished with exit code 2"))
    ev.append((s + 22, "{iso} ERROR airflow.taskinstance - Marking task as FAILED. "
                       "dag_id=file_delivery, task_id=verify_bundle"))
    ev.append((s + 23, "{iso} INFO  airflow.local_task_job - Task exited with return code 2"))
    ev.append((s + 40, "{iso} WARN  file_delivery - delivery to the downstream vendor held pending manual review"))
    ev.append((s + 60, "{iso} ERROR airflow.dagrun - DagRun file_delivery finished with failed tasks"))
    return build(datetime(2026, 7, 26, 22, 15, 0), ev)


# ============================================================ 10 FAILURE_GENERIC
def failure_generic():
    """An application-level assertion the regex has no category for.
    Deliberately omits any non-zero return code line."""
    ev = []
    end = noise(ev, 80, start=0, step=12, dag="month_end_pack")
    s = end + 22
    ev.append((s, "{iso} INFO  airflow.task_runner - Running task month_end_pack.assemble (attempt 1 of 3)"))
    ev.append((s + 6, "{iso} INFO  month_end_pack.assemble - discovered 11 monthly partitions under "
                      "s3://finance-pack/2026/"))
    ev.append((s + 10, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                        "Traceback (most recent call last):",
                        "  File \"/opt/airflow/dags/month_end_pack/assemble.py\", line 140, in execute",
                        "    self._assert_complete(partitions)",
                        "  File \"/opt/airflow/dags/month_end_pack/assemble.py\", line 96, in _assert_complete",
                        "    raise ValueError(msg)",
                        "ValueError: expected 12 monthly partitions for FY2026, found 11 "
                        "(2026-04 absent)"]))
    ev.append((s + 40, "{iso} INFO  airflow.task_runner - Running task month_end_pack.assemble (attempt 2 of 3)"))
    ev.append((s + 46, "{iso} ERROR airflow.taskinstance - Task failed with exception: "
                       "ValueError: expected 12 monthly partitions for FY2026, found 11 (2026-04 absent)"))
    ev.append((s + 80, "{iso} INFO  airflow.task_runner - Running task month_end_pack.assemble (attempt 3 of 3)"))
    ev.append((s + 86, "{iso} ERROR airflow.taskinstance - Task failed with exception: "
                       "ValueError: expected 12 monthly partitions for FY2026, found 11 (2026-04 absent)"))
    ev.append((s + 100, "{iso} INFO  lineage.service - partition 2026-04 was superseded by a restatement "
                        "on 2026-05-02 and never re-registered"))
    ev.append((s + 120, "{iso} ERROR airflow.taskinstance - Marking task as FAILED. "
                        "dag_id=month_end_pack, task_id=assemble"))
    ev.append((s + 124, "{iso} ERROR airflow.dagrun - DagRun month_end_pack finished with failed tasks"))
    return build(datetime(2026, 7, 25, 20, 5, 0), ev)


# ============================================================ 11 UNKNOWN
def unknown_format():
    """A bespoke matching-engine log. No Airflow markers, no known category —
    the regex can say nothing; the agent still has to explain it."""
    ev = []
    for i in range(320):
        s = i * 4
        ev.append((s, "<{isoz}> [SEQ:%06d] MTCH-ENGINE lvl=I code=0x1000 "
                      "msg=\"book rebuilt\" depth=%d spread=%d.%02d"
                      % (100000 + i, 180 + i % 40, i % 3, i % 100)))
        if i % 5 == 0:
            ev.append((s + 1, "<{isoz}> [SEQ:%06d] FEED-GW    lvl=I code=0x1004 "
                              "msg=\"snapshot applied\" seqno=%d lag_us=%d"
                              % (100000 + i, 44000 + i * 3, 120 + i % 90)))
        if i % 7 == 3:
            ev.append((s + 2, "<{isoz}> [SEQ:%06d] RISK-CHK   lvl=I code=0x1010 "
                              "msg=\"limit check ok\" acct=A%04d util=0.%02d"
                              % (100000 + i, 2000 + i, 30 + i % 60)))
    s = 1180
    ev.append((s, "<{isoz}> [SEQ:200001] FEED-GW    lvl=W code=0x2F14 "
                  "msg=\"sequence gap detected\" expected=884120 received=884137 gap=17"))
    ev.append((s + 3, "<{isoz}> [SEQ:200002] FEED-GW    lvl=W code=0x2F14 "
                      "msg=\"sequence gap detected\" expected=884138 received=884191 gap=53"))
    ev.append((s + 8, "<{isoz}> [SEQ:200003] MTCH-ENGINE lvl=E code=0x4A01 "
                      "msg=\"book state divergent, quoting suspended\" symbol=EURUSD"))
    ev.append((s + 11, "<{isoz}> [SEQ:200004] MTCH-ENGINE lvl=E code=0x4A01 "
                       "msg=\"book state divergent, quoting suspended\" symbol=GBPUSD"))
    ev.append((s + 16, "<{isoz}> [SEQ:200005] RISK-CHK   lvl=E code=0x4B22 "
                       "msg=\"stale book, limit checks bypassed\" acct=A2044"))
    ev.append((s + 22, "<{isoz}> [SEQ:200006] SUPERVISOR lvl=F code=0x5000 "
                       "msg=\"quoting halted on 2 symbols pending resync\""))
    for i in range(28):
        ev.append((s + 30 + i * 4, "<{isoz}> [SEQ:%06d] FEED-GW    lvl=W code=0x2F20 "
                                   "msg=\"resync in progress\" pct=%d"
                                   % (200100 + i, min(99, (i + 1) * 4))))
    ev.append((s + 160, "<{isoz}> [SEQ:200200] SUPERVISOR lvl=I code=0x1200 "
                        "msg=\"resync complete, quoting resumed\" halted_for_ms=148220"))
    return build(datetime(2026, 7, 24, 13, 30, 0), ev)


# ============================================================ 12 PASS
def healthy_pass():
    """A clean run with benign warnings only."""
    ev = []
    ev.append((0, "{iso} INFO  airflow.scheduler - Starting DAG run dag_id=daily_pipeline "
                  "run_id=scheduled__2026-07-23T02:00:00"))
    end = noise(ev, 112, start=6, step=13, dag="daily_pipeline")
    ev.append((150, "{iso} WARN  cache.redis - hit ratio 0.76 below target 0.80 (warming after restart)"))
    ev.append((300, "{iso} WARN  archive.uploader - retry 1 of 3 for artifact upload (transient 429), "
                    "succeeded on retry"))
    ev.append((470, "{iso} WARN  airflow.utils.db - pool usage 28/50 (56%) - informational"))
    ev.append((end + 10, "{iso} INFO  daily_pipeline - 46 of 46 tasks succeeded in 12m 04s"))
    ev.append((end + 14, "{iso} INFO  airflow.taskinstance - Marking task as SUCCESS. "
                         "dag_id=daily_pipeline, task_id=notify_owners"))
    ev.append((end + 14, "{iso} INFO  airflow.local_task_job - Task exited with return code 0"))
    ev.append((end + 18, "{iso} INFO  airflow.dagrun - DagRun daily_pipeline finished: 46 succeeded, 0 failed"))
    return build(datetime(2026, 7, 23, 2, 0, 0), ev)


SCENARIOS = [
    ("cat-01-sql-schema-error.log", sql_schema_error, "FAIL / SQL_SCHEMA_ERROR   | high"),
    ("cat-02-sql-syntax-error.log", sql_syntax_error, "FAIL / SQL_SYNTAX_ERROR   | high"),
    ("cat-03-sql-type-mismatch.log", sql_type_mismatch, "FAIL / SQL_TYPE_MISMATCH  | medium"),
    ("cat-04-db-resource-exhaustion.log", db_resource_exhaustion, "FAIL / DB_RESOURCE_EXHAUSTION | critical"),
    ("cat-05-db-connection-error.log", db_connection_error, "FAIL / DB_CONNECTION_ERROR | critical"),
    ("cat-06-permission-error.log", permission_error, "FAIL / PERMISSION_ERROR   | high"),
    ("cat-07-module-import-error.log", module_import_error, "FAIL / MODULE_IMPORT_ERROR | high"),
    ("cat-08-timeout.log", timeout_failure, "FAIL / TIMEOUT            | high"),
    ("cat-09-return-code-failure.log", return_code_failure, "FAIL / RETURN_CODE_FAILURE | medium"),
    ("cat-10-failure-generic.log", failure_generic, "FAIL / FAILURE_GENERIC    | medium"),
    ("cat-11-unknown-format.log", unknown_format, "FAIL / UNKNOWN            | low (bespoke format)"),
    ("cat-12-healthy-pass.log", healthy_pass, "PASS / PASS               | healthy"),
]

if __name__ == "__main__":
    print("Generating classifier-coverage logs into", OUT)
    for name, fn, truth in SCENARIOS:
        write(name, fn(), truth)
