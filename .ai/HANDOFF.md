# Current handoff
Task: T4-03 (G3) Scorer, threshold tuner, run checker, report generator (on STUB data). Attempt 1 (overnight, unattended).
Branch: main
Last commit: 5242566 T4-02: Golden set: 200 labelled synthetic tickets (this run did not commit; the loop commits)
Done: src/score/{__init__,score,tune,check_run,report}.py; tests/test_score.py, test_tune.py, test_check_run.py,
test_replay_regression.py; tests/fixtures/stub_run/ (builder make_STUB_fixtures.py, 18 STUB gold files, STUB manifest,
STUB cost ledger, runs test-local-STUB (passes AB) and dev-local-STUB (pass A)). The STUB request logs now begin with a
marker row, so every fixture file has STUB in its name or first line (Q-27).
Next task: G4 (T4-04) PII redaction and injection scan. G5 and G6 are also unblocked.
Read first: OPEN_QUESTIONS.md Q-25 (run-file contract that G5/G6 must write), Q-26 (scoring/tuning definitions;
(6) the reason prefixes `policy`/`threshold` that G8 must use), Q-27; tests/fixtures/stub_run/make_STUB_fixtures.py.
Do not change: SCORECARD_HEADER and FAILURE_CODES in src/score/score.py (frozen at G3, HARNESS_SPEC §5); STUB fixture
files by hand (edit make_STUB_fixtures.py and rerun it); scripts/.
Tests run / result: `bash scripts/accept.sh G3` → ACCEPT PASS [G3]; `bash scripts/guard.sh` → guard clean;
`python3 -m unittest discover -s tests -t .` → 118 tests OK. The I-8 regression passes vacuously (no committed runs yet).
Open questions: Q-25, Q-26, Q-27 (owner review; cheap to reverse until G9 runs). Q-22…Q-24 from G2 are still open.
