# Current handoff
Task: T4-04 (G4) PII redaction and injection scan (Python reference + JS twin). Attempt 1 (overnight, unattended).
Branch: main
Last commit: d1483c0 T4-03: Scorer, threshold tuner, run checker, report generator (on STUB data) (this run did not
commit; the loop commits)
Done: src/common/redact.py (C-5; `redact_ticket`, `--audit`), src/common/inject.py (C-6, C-7; `scan`, `model_text`,
`scan_and_cap`, `--audit --split`), src/js/redact.js (`redactTicket`) and src/js/inject.js (`scanAndCap`): plain ES2019,
ASCII only, no require/exports. tests/test_redact.py and tests/test_inject.py: vectors, gold audits, node parity on all
200 gold tickets. tests/vectors/{redact,inject}_vectors.json are the shared contract.
Next task: G5 (T4-05) Sink with Jira and Slack sandbox. G6 is also unblocked. G7 pastes src/js/*.js into H3 and H4.
Read first: OPEN_QUESTIONS.md Q-28 (signal names, model_text format, cap on body only, test-split exposure), Q-25 (run-file
contract for G5/G6).
Do not change: the vector files by hand without changing both twins; norm.WHITESPACE (inject.js copies it as escapes);
SCORECARD_HEADER and FAILURE_CODES in src/score/score.py; scripts/.
Tests run / result: `bash scripts/accept.sh G4` → ACCEPT PASS [G4]; `bash scripts/guard.sh` → guard clean;
`python3 -m unittest discover -s tests -t .` → 138 tests OK.
Open questions: Q-28 (new). Q-22…Q-27 are still open.
