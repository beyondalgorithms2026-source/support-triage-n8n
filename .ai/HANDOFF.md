# Current handoff
Task: T4-09 (G9) Dev run and per-class threshold tuning. Attempt 1 (overnight, unattended).
Branch: main
Last commit: 3accb59 T4-08: Full controls: validate, decide, idempotency, Slack, queue, error paths (this run did not commit; the loop commits)
Done: new Config key `tuning_mode` (committed false); `H10 Decide` counts every τ as 0 when it is true (HARNESS_SPEC §3.1).
Live dev run `dev-local-20261013T034424Z-3accb59`: 100 dev tickets, pass A, overrides `tuning_mode=true`,
`llm_max_rpm=120`, 91 model calls, 0 capped; `check_run --phase dev` ok. `python3 -m src.score.tune --run-id <that run>`
wrote `evals/thresholds.json` + `evals/threshold_sweep.csv` (156 rows); `tune --apply` copied τ into `0. Config`.
τ_category: billing/bug/howto 0.50, access 0.75, outage/feature/privacy/other 1.01. τ_priority: P1 0.95, P2 1.01,
P3 0.65, P4 0.50. global_tau 0.50. tests/test_workflow.py: Config τ = thresholds.json, tuning_mode false, H10 tuning test.
Finding: the model over-predicts P2 (31 predicted, 13 correct on dev), so P2 never auto-routes; outage and feature have one
wrong prediction each at full confidence. Recorded in OPEN_QUESTIONS Q-33 (5) for G10/G13.
Next task: G10 (T4-10) Held-out test run, replay proof, scorecard. The test run must not set `tuning_mode`.
Peak dev rate was 28 calls in 60 s against `llm_max_rpm` 30 (Q-33 (2)): check the G10 run for `capped:llm_rpm`.
Read first: OPEN_QUESTIONS.md Q-33, Q-32, Q-26 (6); `evals/thresholds.json`; `evals/threshold_sweep.csv`.
Do not change: τ values in `0. Config` by hand (only `tune --apply`; `tests.test_workflow` and `tune --verify` compare);
`evals/runs/dev-local-20261013T034424Z-3accb59/` (the thresholds trace to it); `LEDGER_HEADER`, `SINK_COLUMNS`/`STAMPS`,
SCORECARD_HEADER, FAILURE_CODES; node name `H6 LLM Classify`; workflow ids; the `first(0)` reads; scripts/.
Tests run / result: `bash scripts/accept.sh G9` → ACCEPT PASS [G9]; `bash scripts/guard.sh` → guard clean;
`python3 -m unittest discover -s tests -t .` → 229 tests OK; `python3 -m compileall -q src tests` → ok.
Open questions: Q-33 (new). Q-2 and Q-22…Q-32 still have no owner answer.
