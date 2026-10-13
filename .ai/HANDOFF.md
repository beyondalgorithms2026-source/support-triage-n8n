# Current handoff
Task: T4-11 (G11) Attack run. Attempt 1 (worker hit a Claude usage limit after the run; daytime session closed out).
Branch: main
Last commit: c7595e4 T4-10: Held-out test run, replay proof, scorecard (before this commit)
Done: live attack run `attack-local-20261013T042634Z-c7595e4`: main segment (48 injection/pii/malformed/duplicate tickets of both splits + 10 originals)
and isolated segments sec12, sec13, writes (Q-35). 104 model calls, $0.0228. `attack_results.json`: 19 defended,
SEC-17 not_run (jira:search_lag never fired). auth_probe.json, secret_scan.json, static_checks.json written.
Next task: G12 (T4-12) Runbook and limitations note.
Read first: OPEN_QUESTIONS.md Q-35, Q-34; `evals/runs/attack-local-20261013T042634Z-c7595e4/attack_results.json`, `summary.json`.
Do not change: `evals/runs/attack-local-20261013T042634Z-c7595e4/`; τ in `0. Config`; frozen headers; node names; workflow ids; scripts/.
Tests run / result: accept.sh G11 → ACCEPT PASS; guard.sh → guard clean; 241 unit tests OK; compileall ok;
static_checks --strict → 0 violations.
Open questions: Q-35 (new). Q-2 and Q-22…Q-34 still have no owner answer.
