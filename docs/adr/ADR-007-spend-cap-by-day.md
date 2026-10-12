## ADR-007: Spend and rate caps enforced before the model call, keyed by server UTC day and by run
Status: Proposed (architecture session; human acceptance pending)
Date: 2026-10-12
Decision:
- H5 refuses the LLM call when `usd_today + est_usd > daily_usd_cap` (UTC day from the server clock), when
  `usd_run + est_usd > run_usd_cap`, or when `calls_last_60s ≥ llm_max_rpm`. Refusal → review, `capped=1`, error row.
- `est_usd` = ceil(chars/3) input tokens + `max_output_tokens`, at Config prices (T2 ADR-002 rule).
- The runner also enforces `RUN_USD_CAP` and a project ceiling `PROJECT_LLM_USD_CAP` from `evals/cost_ledger.csv`
  before starting a run.
- Defaults: run $0.25 (T2 owner override), day $1.00, project $2.00, 30 calls/min.
Reason:
- T2 R-2: a per-run cap keyed by a caller header can be reset by the caller. A server-side daily key closes that.
- Unbounded consumption is cheap to demonstrate and cheap to prevent.
Consequences:
- On a busy real day the daily cap sends tickets to review; the buyer must size it (≈ $0.17 per 1,000 tickets at
  measured-typical length, ARCHITECTURE §10).
- The ledger lookup adds one sink call per ticket. Lookup-then-call is not atomic; concurrent calls can overshoot by
  at most the in-flight calls.
