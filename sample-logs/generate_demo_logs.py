"""Generate long, realistic demo logs with documented ground truth.

Each scenario is built as (offset_seconds, line) events merged onto a timeline,
so the noise-to-signal ratio is realistic: hundreds of routine lines with the
actual story buried inside. Deterministic — no randomness, same bytes every run.

Run:  python3 sample-logs/generate_demo_logs.py

Every FAIL scenario deliberately ends on an Airflow FAIL marker so the regex
classifier (which takes the LAST pass/fail marker) agrees with the agent.
"""

from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).parent


# --------------------------------------------------------------- formatting

def iso(t):                      # 2026-07-28 02:00:01,123
    return t.strftime("%Y-%m-%d %H:%M:%S,") + f"{t.microsecond // 1000:03d}"


def isoz(t):                     # 2026-07-28T02:00:01.123Z
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def syslog(t):                   # Jul 28 02:00:01
    return t.strftime("%b %d %H:%M:%S")


def clf(t):                      # 28/Jul/2026:02:00:01 +0000
    return t.strftime("%d/%b/%Y:%H:%M:%S +0000")


def build(start, events):
    """events: list of (offset_seconds, line_or_lines). Sorted by offset;
    multi-line entries (stack traces) keep their order."""
    out = []
    for offset, payload in sorted(events, key=lambda e: e[0]):
        t = start + timedelta(seconds=offset)
        lines = payload if isinstance(payload, list) else [payload]
        for line in lines:
            out.append(line.format(iso=iso(t), isoz=isoz(t),
                                   sys=syslog(t), clf=clf(t)))
    return "\n".join(out) + "\n"


def write(name, text, ground_truth):
    (OUT / name).write_text(text, encoding="utf-8")
    n = text.count("\n")
    print(f"  {name:42s} {n:4d} lines   {ground_truth}")


# ============================================================== scenario 1
# Nightly ETL: one analytics query hoards the connection pool; three unrelated
# DAGs die of connection starvation. Root cause is NOT the first error line.

def nightly_etl_pool_exhaustion():
    start = datetime(2026, 7, 28, 2, 0, 0)
    ev = []

    dags = [
        ("customer_sync", ["extract_customers", "dedupe_records", "load_dim_customer",
                           "refresh_customer_index", "publish_metrics"]),
        ("inventory_rollup", ["extract_stock", "join_warehouse", "load_facts",
                              "rebuild_aggregates", "notify_downstream"]),
        ("finance_close", ["fetch_ledger", "reconcile_entries", "post_journal",
                           "generate_report"]),
        ("marketing_attrib", ["pull_events", "sessionize", "attribute_touchpoints",
                              "load_attribution"]),
        ("risk_metrics", ["load_exposures", "compute_var", "stress_scenarios",
                          "persist_risk_cube"]),
        ("reference_data", ["sync_instruments", "sync_counterparties", "validate_isins",
                            "expire_stale_records"]),
        ("compliance_feed", ["extract_trades", "screen_sanctions", "build_regulatory_extract"]),
        ("ops_telemetry", ["collect_task_durations", "roll_up_sla", "emit_dashboards"]),
    ]

    ev.append((0, "{iso} INFO  airflow.scheduler - Scheduler heartbeat OK, 4 DAGs eligible for run"))
    ev.append((1, "{iso} INFO  airflow.scheduler - Filling up the DagBag from /opt/airflow/dags"))
    ev.append((2, "{iso} INFO  airflow.utils.db - Connection pool initialised size=50 overflow=10"))

    # --- routine work: dozens of successful task instances (the noise floor)
    offset = 5
    for dag, tasks in dags:
        ev.append((offset, "{iso} INFO  airflow.scheduler - Starting DAG run dag_id=%s "
                           "run_id=scheduled__2026-07-28T02:00:00" % dag))
        offset += 2
        for task in tasks:
            ev.append((offset, "{iso} INFO  airflow.task_runner - Running task %s.%s (attempt 1 of 3)"
                       % (dag, task)))
            ev.append((offset + 1, "{iso} DEBUG airflow.utils.db - Acquired pooled connection "
                                   "(in_use=%d/50)" % (6 + len(ev) % 9)))
            ev.append((offset + 3, "{iso} DEBUG airflow.taskinstance - Dependencies all met for "
                                   "%s.%s, state=queued" % (dag, task)))
            ev.append((offset + 14, "{iso} INFO  %s.%s - processed %d rows in %d.%ds"
                       % (dag, task, 3100 + len(ev) * 47, 9 + len(ev) % 14, len(ev) % 10)))
            ev.append((offset + 22, "{iso} INFO  airflow.taskinstance - Marking task as SUCCESS. "
                                    "dag_id=%s, task_id=%s, duration=21.%ds" % (dag, task, len(ev) % 10)))
            ev.append((offset + 22, "{iso} INFO  airflow.local_task_job - Task exited with return code 0"))
            offset += 14

    # more background chatter interleaved through the whole window
    for i in range(72):
        s = 20 + i * 15
        ev.append((s, "{iso} INFO  airflow.scheduler - Heartbeat: %d running, %d queued, %d success today"
                   % (4 - i % 3, i % 5, 118 + i)))
        ev.append((s + 4, "{iso} DEBUG airflow.executor - Sent task instance to CeleryExecutor queue=default"))
        if i % 3 == 0:
            ev.append((s + 6, "{iso} DEBUG airflow.utils.db - Released pooled connection "
                              "(in_use=%d/50)" % (7 + i % 21)))
        if i % 4 == 0:
            ev.append((s + 9, "{sys} prod-db-01 postgres[%d]: LOG:  checkpoint starting: time" % (4200 + i)))
            ev.append((s + 11, "{sys} prod-db-01 postgres[%d]: LOG:  checkpoint complete: wrote %d buffers"
                       % (4200 + i, 1820 + i * 37)))
        if i % 5 == 2:
            ev.append((s + 12, "{iso} INFO  airflow.dagrun - DagRun state refreshed, 0 tasks in deferred state"))
        if i % 6 == 1:
            ev.append((s + 13, "{sys} prod-db-01 postgres[%d]: LOG:  automatic vacuum of table "
                               "\"warehouse.public.stg_events\": index scans: 1" % (4600 + i)))
        if i % 8 == 5:
            ev.append((s + 7, "{iso} INFO  airflow.metrics - emitted 42 statsd gauges to metrics-relay:8125"))
        if i % 9 == 4:
            ev.append((s + 10, "{iso} DEBUG celery.worker - Task accepted by worker-%02d pid=%d"
                       % (i % 6, 21000 + i)))

    # --- ROOT CAUSE: one analytics statement holds 40 connections open
    ev.append((840, "{iso} INFO  airflow.task_runner - Running task analytics_daily.daily_revenue_rollup (attempt 1 of 3)"))
    ev.append((842, "{sys} prod-db-01 postgres[5001]: LOG:  statement: BEGIN; SET work_mem='2GB'; "
                    "INSERT INTO warehouse.daily_revenue SELECT * FROM staging.revenue_wide"))
    ev.append((845, "{iso} INFO  analytics.runner - daily_revenue_rollup opened 40 parallel writer connections"))
    ev.append((860, "{iso} WARN  airflow.utils.db - Connection pool usage 42/50 (84%) - above warn threshold 80%"))
    ev.append((880, "{sys} prod-db-01 postgres[5001]: LOG:  duration: 38221.114 ms  statement: "
                    "INSERT INTO warehouse.daily_revenue SELECT * FROM staging.revenue_wide"))
    ev.append((890, "{iso} WARN  airflow.utils.db - Connection pool usage 47/50 (94%) - above warn threshold 80%"))
    ev.append((900, "{iso} WARN  airflow.utils.db - Connection pool usage 50/50 (100%) - overflow connections in use 4/10"))
    ev.append((905, "{sys} prod-db-01 postgres[5002]: LOG:  duration: 41903.882 ms  statement: "
                    "UPDATE warehouse.daily_revenue SET reconciled = true WHERE batch_id = 20260728"))

    # --- CASCADE: three unrelated DAGs starve
    victims = [
        (920, "inventory_rollup", "load_facts"),
        (947, "finance_close", "post_journal"),
        (982, "marketing_attrib", "attribute_touchpoints"),
    ]
    for s, dag, task in victims:
        ev.append((s, "{iso} INFO  airflow.task_runner - Running task %s.%s (attempt 1 of 3)" % (dag, task)))
        ev.append((s + 4, "{sys} prod-db-01 postgres[%d]: FATAL:  remaining connection slots are reserved "
                          "for non-replication superuser connections" % (5100 + s)))
        ev.append((s + 5, ["{iso} ERROR airflow.taskinstance - Task failed with exception",
                           "psycopg2.OperationalError: connection to server at \"prod-db-01\" "
                           "(10.30.2.11), port 5432 failed: FATAL:  remaining connection slots are "
                           "reserved for non-replication superuser connections",
                           "    at /opt/airflow/dags/%s/%s.py, line 88, in execute" % (dag, task),
                           "    session = get_session(pool='airflow_default')"]))
        ev.append((s + 7, "{iso} WARN  airflow.taskinstance - Task %s.%s up for retry: 1 of 3" % (dag, task)))
        ev.append((s + 40, "{iso} ERROR airflow.taskinstance - Task failed with exception "
                           "(attempt 2 of 3): could not connect to server"))
        ev.append((s + 75, "{iso} ERROR airflow.taskinstance - Task failed with exception "
                           "(attempt 3 of 3): could not connect to server"))

    ev.append((1010, "{iso} WARN  airflow.scheduler - 3 DAG runs now in state 'running' past their SLA"))
    ev.append((1040, "{iso} INFO  analytics.runner - daily_revenue_rollup committed 8.1M rows, releasing connections"))
    ev.append((1042, "{iso} INFO  airflow.utils.db - Connection pool usage 11/50 (22%) - recovered"))

    # final markers: the run ends in failure (classifier reads the LAST marker)
    for i, (s, dag, task) in enumerate(victims):
        ev.append((1200 + i * 3, "{iso} ERROR airflow.taskinstance - Marking task as FAILED. "
                                 "dag_id=%s, task_id=%s, execution_date=2026-07-28T02:00:00" % (dag, task)))
        ev.append((1200 + i * 3, "{iso} INFO  airflow.local_task_job - Task exited with return code 1"))
    ev.append((1215, "{iso} ERROR airflow.dagrun - DagRun finished with failed tasks: "
                     "inventory_rollup, finance_close, marketing_attrib"))
    ev.append((1216, "{iso} INFO  airflow.scheduler - Scheduler heartbeat OK, 0 DAGs eligible for run"))

    return build(start, ev)


# ============================================================== scenario 2
# Bad deploy: v4.7.2 introduces a null-pointer path that only fires for orders
# carrying a promo code. Error rate climbs; nobody rolls back.

def payments_deploy_regression():
    start = datetime(2026, 7, 24, 13, 55, 0)
    ev = []

    endpoints = ["/v1/charges", "/v1/refunds", "/v1/customers", "/v1/payment_methods",
                 "/v1/payouts", "/v1/balance"]
    for i in range(84):
        s = i * 10          # normal traffic continues right through the incident
        ep = endpoints[i % len(endpoints)]
        ev.append((s, "{isoz} INFO  [payments-api] POST %s 201 %dms merchant=%d"
                   % (ep, 61 + (i * 7) % 40, 4400 + i)))
        ev.append((s + 2, "10.42.1.%d - - [{clf}] \"POST %s HTTP/1.1\" 201 412 \"-\" \"stripe-go/2.4\""
                   % (20 + i % 30, ep)))
        if i % 3 == 0:
            ev.append((s + 3, "{isoz} INFO  [payments-worker] settled batch id=%d entries=%d"
                       % (99100 + i, 40 + i)))
        if i % 4 == 1:
            ev.append((s + 4, "{isoz} DEBUG [payments-api] cache hit ratio 0.9%d over last 1000 requests" % (i % 9)))
        if i % 5 == 2:
            ev.append((s + 1, "{isoz} DEBUG [ledger-writer] appended %d entries to journal shard %d"
                       % (12 + i % 30, i % 8)))
        if i % 7 == 3:
            ev.append((s + 3, "{sys} pay-node-%02d systemd[1]: payments-api.service: healthy, "
                              "memory 412.%dM of 2.0G" % (i % 4, i % 10)))
        if i % 9 == 5:
            ev.append((s + 2, "{isoz} INFO  [fraud-scorer] scored transaction %d risk=0.0%d allow"
                       % (770000 + i, i % 9)))

    # deploy marker — the pivot point of the whole story
    ev.append((420, "{isoz} INFO  [deploy-agent] Deployment started: payments-api v4.7.2 "
                    "(commit 7a41f9c, author c.lorenzo-pavon, MR !214)"))
    ev.append((423, "{isoz} INFO  [deploy-agent] Draining connections from payments-api-7d9f4 (v4.7.1)"))
    ev.append((448, "{isoz} INFO  [k8s.deployment] payments-api rollout: 1/3 pods updated to v4.7.2"))
    ev.append((472, "{isoz} INFO  [k8s.deployment] payments-api rollout: 3/3 pods updated to v4.7.2"))
    ev.append((474, "{isoz} INFO  [deploy-agent] Deployment finished: payments-api v4.7.2 is live"))
    ev.append((478, "{isoz} INFO  [health-checker] payments-api liveness OK (3/3 pods ready)"))

    npe = ["{isoz} ERROR [payments-api] Unhandled exception processing POST /v1/charges",
           "java.lang.NullPointerException: Cannot invoke \"PromotionRule.discountFor(Order)\" "
           "because \"rule\" is null",
           "\tat com.ubs.payments.pricing.PricingEngine.applyPromotions(PricingEngine.java:214)",
           "\tat com.ubs.payments.pricing.PricingEngine.total(PricingEngine.java:96)",
           "\tat com.ubs.payments.api.ChargeController.create(ChargeController.java:63)",
           "\tat java.base/java.lang.Thread.run(Thread.java:1583)"]

    fails = [500, 519, 544, 571, 588, 615, 641, 668, 690, 717, 742, 769]
    for i, s in enumerate(fails):
        ev.append((s, npe))
        ev.append((s + 1, "10.42.1.%d - - [{clf}] \"POST /v1/charges HTTP/1.1\" 500 87 \"-\" \"stripe-go/2.4\""
                   % (60 + i)))
        # healthy traffic continues in parallel — only promo-code orders break
        ev.append((s + 5, "{isoz} INFO  [payments-api] POST /v1/charges 201 %dms merchant=%d"
                   % (58 + i, 4500 + i)))
        if i % 3 == 2:
            ev.append((s + 7, "{isoz} INFO  [payments-worker] settled batch id=%d entries=%d"
                       % (99200 + i, 33 + i)))

    ev.append((560, "{isoz} WARN  [alerting] payments-api 5xx rate 18% over last 1m (threshold 2%)"))
    ev.append((620, "{isoz} WARN  [alerting] payments-api 5xx rate 27% over last 1m (threshold 2%)"))
    ev.append((700, "{isoz} WARN  [alerting] PagerDuty incident PD-8841 opened for payments-api"))
    ev.append((733, "{isoz} INFO  [support-bot] 14 customer reports of \"payment failed\" in 10 minutes"))
    ev.append((760, "{isoz} WARN  [payments-api] circuit breaker for pricing-engine now HALF_OPEN"))

    ev.append((800, "{isoz} ERROR [batch-runner] Task failed with exception: downstream payments-api "
                    "returned 500 for 12 of 40 settlement retries"))
    ev.append((802, "{isoz} ERROR [batch-runner] Marking task as FAILED. dag_id=settlement_replay, "
                    "task_id=retry_failed_charges"))
    ev.append((803, "{isoz} INFO  [batch-runner] Task exited with return code 1"))
    return build(start, ev)


# ============================================================== scenario 3
# Schema drift: migration 0042 half-applied after a lock timeout, so every dbt
# model referencing the new column fails.

def warehouse_schema_drift():
    start = datetime(2026, 7, 26, 5, 30, 0)
    ev = []

    ev.append((0, "{iso} INFO  migrate.runner - Applying migration 0042_add_customer_segment"))
    ev.append((3, "{sys} warehouse-db postgres[7701]: LOG:  statement: ALTER TABLE dim_customer "
                  "ADD COLUMN customer_segment varchar(32)"))
    ev.append((8, "{sys} warehouse-db postgres[7701]: LOG:  process 7701 still waiting for "
                  "AccessExclusiveLock on relation 18442 after 5000.114 ms"))
    ev.append((63, "{sys} warehouse-db postgres[7701]: ERROR:  canceling statement due to lock timeout"))
    ev.append((64, "{iso} ERROR migrate.runner - Migration 0042 aborted after lock timeout; "
                   "ROLLBACK issued for statement 2 of 3"))
    ev.append((65, "{iso} WARN  migrate.runner - Migration 0042 left in PARTIAL state: "
                   "dim_customer_segment_lookup created, dim_customer.customer_segment NOT created"))
    ev.append((66, "{iso} INFO  migrate.runner - Migration runner exiting, 1 partial / 0 applied"))

    models = ["stg_orders", "stg_customers", "stg_payments", "stg_shipments", "stg_returns",
              "stg_promotions", "stg_inventory", "stg_suppliers", "int_order_items",
              "int_customer_activity", "int_payment_matching", "int_shipment_legs",
              "dim_date", "dim_product", "dim_supplier", "dim_channel", "dim_geography",
              "fct_orders", "fct_payments", "fct_shipments", "fct_returns",
              "mart_daily_sales", "mart_channel_perf", "mart_supplier_scorecard",
              "mart_inventory_health", "mart_returns_analysis",
              "stg_warehouse_bins", "stg_carrier_events", "stg_price_history",
              "int_carrier_sla", "int_price_changes", "int_stock_movements",
              "dim_carrier", "dim_warehouse", "dim_promotion", "dim_currency",
              "fct_stock_movements", "fct_price_changes", "fct_carrier_sla",
              "mart_logistics_perf", "mart_pricing_effectiveness", "mart_promo_uplift",
              "snap_inventory_daily", "snap_orders_hourly"]
    for i, model in enumerate(models):
        s = 90 + i * 11
        ev.append((s, "{iso} INFO  dbt.runner - %d of 64 START model warehouse.%s" % (i + 1, model)))
        ev.append((s + 4, "{iso} INFO  dbt.runner - %d of 64 OK created table model warehouse.%s "
                          "[SELECT %d in %d.%02ds]" % (i + 1, model, 1200 + i * 813, 2 + i % 9, (i * 7) % 100)))
        if i % 3 == 0:
            ev.append((s + 6, "{iso} DEBUG dbt.adapter - Acquiring connection 'model.warehouse.%s'" % model))
        if i % 4 == 1:
            ev.append((s + 7, "{sys} warehouse-db postgres[%d]: LOG:  duration: %d.%03d ms  statement: "
                              "CREATE TABLE warehouse.%s AS SELECT ..." % (7900 + i, 400 + i * 61, i, model)))
        if i % 5 == 2:
            ev.append((s + 8, "{iso} INFO  dbt.runner - Concurrency: 8 threads (target='prod')"))
        if i % 6 == 4:
            ev.append((s + 9, "{iso} DEBUG dbt.compiler - Compiled node warehouse.%s in 0.0%dms" % (model, i % 9)))

    broken = [("dim_customer_enriched", 420), ("fct_orders_segmented", 486),
              ("mart_customer_ltv", 553), ("mart_segment_revenue", 620),
              ("rpt_exec_dashboard", 688)]
    for name, s in broken:
        ev.append((s, "{iso} INFO  dbt.runner - Running model warehouse.%s" % name))
        ev.append((s + 3, ["{iso} ERROR dbt.runner - Database Error in model %s (models/marts/%s.sql)" % (name, name),
                           "  column \"customer_segment\" does not exist",
                           "  LINE 14:   d.customer_segment AS segment,",
                           "                ^",
                           "  HINT:  Perhaps you meant to reference the column \"d.customer_segment_id\".",
                           "  compiled SQL at target/run/warehouse/models/marts/%s.sql" % name]))
        ev.append((s + 6, "{sys} warehouse-db postgres[%d]: ERROR:  column \"customer_segment\" does not exist "
                          "at character 288" % (7800 + s)))
        # unquoted + psycopg2 form so the regex classifier lands on SQL_SCHEMA_ERROR
        ev.append((s + 7, "{iso} ERROR dbt.adapter - psycopg2.errors.UndefinedColumn: "
                          "column dim_customer.customer_segment does not exist"))

    ev.append((730, "{iso} WARN  dbt.runner - 5 of 38 models FAILED, 33 completed successfully"))
    ev.append((740, "{iso} ERROR airflow.taskinstance - Task failed with exception: dbt exited non-zero"))
    ev.append((742, "{iso} ERROR airflow.taskinstance - Marking task as FAILED. dag_id=warehouse_build, "
                    "task_id=dbt_run_marts"))
    ev.append((743, "{iso} INFO  airflow.local_task_job - Task exited with return code 1"))
    return build(start, ev)


# ============================================================== scenario 4
# Healthy run. Benign warnings only. Proves the agent does not invent problems.

def healthy_nightly_close():
    start = datetime(2026, 7, 25, 1, 0, 0)
    ev = []

    ev.append((0, "{iso} INFO  airflow.scheduler - Starting DAG run dag_id=nightly_close "
                  "run_id=scheduled__2026-07-25T01:00:00"))
    tasks = ["snapshot_balances", "fetch_fx_rates", "revalue_positions", "match_trades",
             "post_adjustments", "reconcile_cash", "generate_statements", "archive_artifacts",
             "publish_close_metrics", "notify_controllers"]
    offset = 4
    for i, task in enumerate(tasks):
        ev.append((offset, "{iso} INFO  airflow.task_runner - Running task nightly_close.%s (attempt 1 of 3)" % task))
        ev.append((offset + 2, "{iso} DEBUG airflow.utils.db - Acquired pooled connection (in_use=%d/50)" % (4 + i)))
        ev.append((offset + 14, "{iso} INFO  nightly_close.%s - processed %d records in %d.%ds"
                   % (task, 12000 + i * 3110, 11 + i, i % 10)))
        ev.append((offset + 28, "{iso} INFO  airflow.taskinstance - Marking task as SUCCESS. "
                                "dag_id=nightly_close, task_id=%s, duration=27.%ds" % (task, i)))
        ev.append((offset + 28, "{iso} INFO  airflow.local_task_job - Task exited with return code 0"))
        offset += 34

    for i in range(64):
        s = 12 + i * 6
        ev.append((s, "{iso} INFO  airflow.scheduler - Heartbeat: 1 running, 0 queued, %d success today" % (40 + i)))
        if i % 3 == 0:
            ev.append((s + 2, "{iso} DEBUG airflow.executor - Task slot released, 15 of 16 slots free"))
        if i % 4 == 1:
            ev.append((s + 3, "{sys} prod-db-02 postgres[%d]: LOG:  checkpoint complete: wrote %d buffers"
                       % (3300 + i, 900 + i * 44)))
        if i % 5 == 2:
            ev.append((s + 4, "{iso} DEBUG cache.redis - keyspace hit ratio 0.8%d, evicted 0 keys" % (5 + i % 5)))
        if i % 6 == 3:
            ev.append((s + 4, "{iso} INFO  audit.trail - user=svc-close action=write resource=ledger result=allow"))
        if i % 7 == 5:
            ev.append((s + 5, "{sys} prod-db-02 postgres[%d]: LOG:  automatic analyze of table "
                              "\"finance.public.ledger_entries\"" % (3500 + i)))
        if i % 9 == 6:
            ev.append((s + 2, "{iso} INFO  fx.client - refreshed %d currency pairs from provider" % (28 + i % 6)))

    # benign warnings a naive tool would flag; the agent should not
    ev.append((120, "{iso} WARN  cache.redis - cache hit ratio 0.74 below target 0.80 (warming after restart)"))
    ev.append((260, "{iso} WARN  fx.client - rate provider responded in 1840ms (soft threshold 1500ms), "
                    "response accepted"))
    ev.append((410, "{iso} WARN  archive.uploader - retry 1 of 3 for artifact upload (transient 429), "
                    "succeeded on retry"))
    ev.append((560, "{iso} WARN  airflow.utils.db - Connection pool usage 31/50 (62%) - informational"))

    ev.append((offset + 10, "{iso} INFO  airflow.dagrun - DagRun nightly_close finished: 10 succeeded, 0 failed"))
    ev.append((offset + 12, "{iso} INFO  close.reporter - Close package published to "
                            "s3://finance-close/2026-07-25/close_pack.pdf"))
    ev.append((offset + 14, "{iso} INFO  airflow.taskinstance - Marking task as SUCCESS. "
                            "dag_id=nightly_close, task_id=notify_controllers, duration=2.1s"))
    ev.append((offset + 14, "{iso} INFO  airflow.local_task_job - Task exited with return code 0"))
    return build(start, ev)


# ============================================================== scenario 5
# The log-agnostic showpiece: six different formats in one file. Root cause is
# an unrotated WAL volume filling the disk, three layers below the symptoms.

def platform_disk_cascade():
    start = datetime(2026, 7, 22, 3, 30, 0)
    ev = []

    for i in range(72):
        s = i * 9      # traffic runs the whole window, before and during the outage
        ev.append((s, "10.60.2.%d - - [{clf}] \"GET /api/v2/portfolio/%d HTTP/1.1\" 200 %d \"-\" "
                      "\"Mozilla/5.0\"" % (11 + i % 40, 88000 + i, 1400 + i * 13)))
        ev.append((s + 2, "{isoz} INFO  [portfolio-api] served portfolio %d in %dms" % (88000 + i, 22 + i % 30)))
        if i % 3 == 0:
            ev.append((s + 3, '{{"ts":"{isoz}","level":"info","svc":"pricing-engine",'
                              '"msg":"revalued %d instruments","latency_ms":%d}}' % (1200 + i * 5, 90 + i)))
        if i % 4 == 1:
            ev.append((s + 4, "{sys} node-07 systemd[1]: Started Session %d of user svc-portfolio." % (2200 + i)))
        if i % 5 == 3:
            ev.append((s + 5, "{iso} INFO  audit.trail - user=svc-portfolio action=read resource=positions "
                              "result=allow"))
        if i % 6 == 2:
            ev.append((s + 6, '{{"ts":"{isoz}","level":"debug","svc":"settlement-service",'
                              '"msg":"queue depth","depth":%d,"consumers":4}}' % (3 + i % 12)))
        if i % 7 == 4:
            ev.append((s + 1, "{isoz} INFO  [portfolio-api] cache warm: %d entries, hit ratio 0.9%d"
                       % (5400 + i * 11, i % 9)))
        if i % 8 == 5:
            ev.append((s + 7, "{sys} node-07 kernel: [188%d.112] nvme0n1: I/O queue depth %d, "
                              "avg latency 0.%dms" % (2000 + i, 8 + i % 20, i % 9)))

    # ROOT CAUSE, quiet and early: WAL archiving stopped 40 minutes ago
    ev.append((150, "{sys} node-07 postgres[9001]: WARNING:  archive_command failed with exit code 1; "
                    "WAL segment 0000000100000A2F000000B4 retained"))
    ev.append((151, "{sys} node-07 postgres[9001]: DETAIL:  rsync: connection unexpectedly closed "
                    "(archive host wal-archive-01 unreachable)"))
    ev.append((260, "{sys} node-07 kernel: [1882913.442] EXT4-fs (nvme0n1p3): warning: "
                    "/var/lib/postgresql 84% full"))
    ev.append((300, "{iso} WARN  diskmon - /var/lib/postgresql at 88% (412GB/468GB), "
                    "WAL directory growing 1.4GB/min"))
    ev.append((340, "{iso} WARN  diskmon - /var/lib/postgresql at 94% (440GB/468GB)"))
    ev.append((372, "{iso} WARN  diskmon - /var/lib/postgresql at 99% (463GB/468GB) - "
                    "CRITICAL threshold breached"))

    # the disk fills: first real failure
    ev.append((392, "{sys} node-07 kernel: [1883155.009] EXT4-fs (nvme0n1p3): "
                    "no space left on device writing to inode 918224"))
    ev.append((394, "{sys} node-07 postgres[9001]: PANIC:  could not write to file "
                    "\"pg_wal/xlogtemp.9001\": No space left on device"))
    ev.append((396, "{sys} node-07 postgres[9001]: LOG:  server process (PID 9001) was terminated by signal 6: Aborted"))
    ev.append((398, "{sys} node-07 postgres[1]: LOG:  database system is in recovery mode"))

    # layer 2: services that depend on the database
    ev.append((404, ["{isoz} ERROR [portfolio-api] database write failed, entering degraded mode",
                     "psycopg2.OperationalError: server closed the connection unexpectedly",
                     "\tThis probably means the server terminated abnormally",
                     "\tbefore or while processing the request."]))
    ev.append((408, '{{"ts":"{isoz}","level":"error","svc":"pricing-engine",'
                    '"msg":"could not persist valuation batch","err":"connection reset by peer",'
                    '"batch_id":44120}}'))
    ev.append((412, "{isoz} ERROR [settlement-service] Connection to postgres://node-07:5432/platform "
                    "refused (ECONNREFUSED)"))
    ev.append((418, "{sys} node-07 systemd[1]: pricing-engine.service: Main process exited, "
                    "code=exited, status=1/FAILURE"))
    ev.append((420, "{sys} node-07 systemd[1]: pricing-engine.service: Scheduled restart job, restart counter is at 1."))

    # layer 3: user-visible failures
    for i, s in enumerate([424, 431, 439, 448, 457, 466, 478, 489]):
        ev.append((s, "10.60.2.%d - - [{clf}] \"GET /api/v2/portfolio/%d HTTP/1.1\" 503 0 \"-\" \"Mozilla/5.0\""
                   % (11 + i, 88100 + i)))
        ev.append((s + 2, "{isoz} ERROR [portfolio-api] upstream unavailable: pricing-engine "
                          "returned 503 after %dms" % (2000 + i * 11)))
    ev.append((470, ["{iso} ERROR client.sdk - Traceback (most recent call last):",
                     "  File \"/opt/reporting/run_eod.py\", line 212, in fetch_positions",
                     "    resp = session.get(url, timeout=30)",
                     "  File \"/usr/lib/python3.12/site-packages/requests/sessions.py\", line 602, in get",
                     "    return self.request(\"GET\", url, **kwargs)",
                     "requests.exceptions.HTTPError: 503 Server Error: Service Unavailable for url: "
                     "http://portfolio-api/api/v2/portfolio/88104"]))

    ev.append((500, "{isoz} WARN  [alerting] SEV-1 declared: platform read path unavailable, "
                    "8 services reporting errors"))
    ev.append((520, "{iso} INFO  oncall.bot - Paged: platform-sre (primary), dba-oncall (secondary)"))
    ev.append((548, "{sys} node-07 postgres[1]: LOG:  recovery stalled: cannot write WAL, "
                    "device still full"))

    ev.append((600, "{iso} ERROR airflow.taskinstance - Task failed with exception: "
                    "eod_reporting could not reach portfolio-api after 3 attempts"))
    ev.append((602, "{iso} ERROR airflow.taskinstance - Marking task as FAILED. dag_id=eod_reporting, "
                    "task_id=fetch_positions"))
    ev.append((603, "{iso} INFO  airflow.local_task_job - Task exited with return code 1"))
    return build(start, ev)


SCENARIOS = [
    ("nightly-etl-pool-exhaustion.log", nightly_etl_pool_exhaustion,
     "FAIL / DB_RESOURCE_EXHAUSTION - root cause: daily_revenue_rollup holds 40 conns"),
    ("payments-deploy-regression.log", payments_deploy_regression,
     "FAIL / FAILURE_GENERIC - root cause: deploy v4.7.2 NPE in PricingEngine:214"),
    ("warehouse-schema-drift.log", warehouse_schema_drift,
     "FAIL / SQL_SCHEMA_ERROR - root cause: migration 0042 partial, column missing"),
    ("healthy-nightly-close.log", healthy_nightly_close,
     "PASS - no incidents; benign warnings only"),
    ("platform-disk-cascade.log", platform_disk_cascade,
     "FAIL / DB_CONNECTION_ERROR - root cause: WAL archive failure filled the disk"),
]

if __name__ == "__main__":
    print("Generating demo logs into", OUT)
    for name, fn, truth in SCENARIOS:
        write(name, fn(), truth)
