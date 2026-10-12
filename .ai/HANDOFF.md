# Current handoff
Task: T4-06 (G6) Replay runner. Attempt 1 (overnight, unattended).
Branch: main
Last commit: 4ad565b T4-05: Sink with Jira and Slack sandbox (this run did not commit; the loop commits)
Done: src/replay/run.py. `setup` builds `t4-llm`, `t4-webhook-auth`, `t4-sink-auth`, `t4-slack` (httpHeaderAuth) and
`t4-jira` (httpBasicAuth) in memory and pipes them to `docker exec -i <N8N_CONTAINER> n8n import:credentials
--input=/dev/stdin`. `run --phase P [--split] [--ids] [--limit] [--passes] [--force-fault id:target:mode[:pass]]
[--config-override k=v]`: project-cap, split, static-check and Config-vs-.env checks before any side effect; in-memory
overrides, credential binding by name and placeholder substitution; handler then workflow import + publish; in-process
sink (`make_server`, port SINK_PORT); per ticket `/_replay/active`, gold or forced fault, webhook POST, execution read
from SQLite read-only, trace rows (H6 rows carry tokens, usd, `llm_input`); runner cap before each ticket; unpublish
and sink stop in `finally`; `summary.json` (Q-25 fields + `aborted`), one `evals/cost_ledger.csv` row. n8n version is
read with `n8n --version` in the container. tests/test_replay.py: 13 tests (fake n8n, real sink on an ephemeral port).
Next task: G7 (T4-07) Thin end-to-end slice. Run `python3 -m src.replay.run setup`, then
`python3 -m src.replay.run run --phase slice --split dev --limit 10 --ids <first 10 dev clean>`.
Read first: OPEN_QUESTIONS.md Q-30 (credential types for HTTP nodes; H6 input item must carry `model_text`;
`0. Config` caps and prices must equal .env), Q-29 (sink contract), Q-25 (run-file contract).
Do not change: `LEDGER_HEADER` in src/replay/run.py (HARNESS_SPEC §5, frozen); `SINK_COLUMNS` / `STAMPS` in
src/sink/server.py; SCORECARD_HEADER and FAILURE_CODES in src/score/score.py; scripts/.
Tests run / result: `bash scripts/accept.sh G6` → ACCEPT PASS [G6]; `bash scripts/guard.sh` → guard clean;
`python3 -m unittest discover -s tests -t .` → 177 tests OK.
Open questions: Q-30 (new). Q-22…Q-29 are still open.
