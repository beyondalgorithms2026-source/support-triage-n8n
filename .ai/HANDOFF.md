# Current handoff
Task: T4-05 (G5) Sink with Jira and Slack sandbox. Attempt 1 (overnight, unattended).
Branch: main
Last commit: d853ee7 T4-04: PII redaction and injection scan (Python reference + JS twin) (this run did not commit;
the loop commits)
Done: src/sink/server.py: `make_server(state_dir, sink_token, jira_email, jira_token, slack_token, host, port,
project_key, channels)` and `main` (`python3 -m src.sink.server --state-dir <run>/sink`, env names only, exit 2 when a
secret is unset). Sink routes `/append/<table>`, `/lookup/<table>?col=a|b`, `/ledger/sum?day=|run_id=`,
`/ledger/count?since_s=`, `/_replay/active`, `/_replay/fault`, `/_replay/llm_input`, `/_health`. Jira
`GET /rest/api/3/search/jql`, `POST /rest/api/3/issue`; Slack `POST /api/chat.postMessage`. Tables `sink/<table>.csv`
with stamps `sink_seq, sink_ts, replay_input_id, replay_pass`; `requests.jsonl` (no headers). tests/test_sink.py: 26
tests, incl. a check that `src.score.score.Run` reads the sink folder (Q-25).
Next task: G6 (T4-06) Replay runner. Start the sink with `make_server(..., port=SINK_PORT)` per run; call
`/_replay/active` before each ticket, then `/_replay/fault` with the gold `fault` (`target`, `mode`, `pass`).
Read first: OPEN_QUESTIONS.md Q-29 (sink contract choices: 403 codes, fault lifetime, search_lag, llm_input route),
Q-25 (run-file contract).
Do not change: `SINK_COLUMNS` / `SANDBOX_COLUMNS` / `STAMPS` in src/sink/server.py (ARCHITECTURE §6.3, frozen);
SCORECARD_HEADER and FAILURE_CODES in src/score/score.py; scripts/.
Tests run / result: `bash scripts/accept.sh G5` → ACCEPT PASS [G5]; `bash scripts/guard.sh` → guard clean;
`python3 -m unittest discover -s tests -t .` → 164 tests OK.
Open questions: Q-29 (new). Q-22…Q-28 are still open.
