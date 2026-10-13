# Current handoff
Task: T4-10 (G10) Held-out test run, replay proof, scorecard. Attempt 1 (overnight, unattended).
Branch: main
Last commit: 0814c13 T4-09: Dev run and per-class threshold tuning (this run did not commit; the loop commits)
Done: H2 change before the run (Q-34 (1)): `H2 Content Lookup` also matches `error`; `H2 Dedupe Check` counts an
`error` row only with an `issue_key`. Without it, gold `sink:jira_links:503` on t4-075 made pass B call the model.
Live run `test-local-20261013T040225Z-0814c13`: 100 test tickets, passes AB, override `llm_max_rpm=120` (Q-34 (2)),
93 model calls in pass A, 0 in pass B, 0 pass-B issues, 0 capped, $0.0105318. t4-075: pass A `error` SUP-9, pass B
`duplicate_skip` SUP-9. `score` wrote `evals/scorecard.csv` (100 rows) and both confusion CSVs.
`src/score/score.py` `read_csv` reads NUL as U+FFFD: t4-198 put NUL into `review_queue.csv` (Q-34 (4)).
Findings for G12/G13 (Q-34 (3)): pass A 72 review / 20 auto_routed; 21 gold P3 predicted P2 (P2 τ 1.01); peak 37 model
calls in 60 s, so the committed `llm_max_rpm` 30 would cap; sink writes control characters raw into CSV.
Next task: G11 (T4-11) Attack run.
Read first: OPEN_QUESTIONS.md Q-34, Q-33, Q-32 (3); `evals/runs/test-local-20261013T040225Z-0814c13/summary.json`.
Do not change: τ in `0. Config` (I-9; no re-tune on test); `evals/runs/test-local-20261013T040225Z-0814c13/` (the
scorecard traces to it); `LEDGER_HEADER`, `SINK_COLUMNS`/`STAMPS`, SCORECARD_HEADER, FAILURE_CODES; node names;
workflow ids; the `first(0)` reads; scripts/.
Tests run / result: `bash scripts/accept.sh G10` → ACCEPT PASS [G10]; `bash scripts/guard.sh` → guard clean;
`python3 -m unittest discover -s tests -t .` → 232 tests OK; `python3 -m compileall -q src tests` → ok;
`python3 -m src.checks.static_checks --strict` on t4-triage.json → 0 violations.
Open questions: Q-34 (new). Q-2 and Q-22…Q-33 still have no owner answer.
