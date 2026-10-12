# Current handoff
Task: T4-01 (G1) Harness skeleton, normalisers, static checks. Attempt 1 (overnight, unattended).
Branch: main
Last commit: 2deeb3d T4-00: plan (this run did not commit; the loop commits)
Done: package skeleton (src/, src/common/, src/checks/, tests/); src/common/norm.py (text_norm, email_norm,
dedupe_key, content_sha256); src/checks/static_checks.py (T2 port + allowed-host prefixes, no $env, Jira create
retryOnFail false, Jira/Slack path report, --allowed-hosts); tests/test_norm.py; tests/test_static_checks.py.
Next task: G2 (T4-02) Golden set — if the loop's accept.sh G1 + guard.sh pass. If they fail, G1 attempt 2 fixes them.
Read first: OPEN_QUESTIONS.md Q-19…Q-21; tests/test_norm.py vectors (JS twin contract for G7).
Do not change: norm.WHITESPACE and the preimage format without a G2 gold regeneration; frozen formats in
docs/HARNESS_SPEC.md; scripts/ (protected).
Tests run / result: none. The Bash tool was denied in this run, so unittest, compileall, accept.sh G1 and guard.sh
were not run, and git status was not checked.
Open questions: Q-19 (normaliser details), Q-20 (static checker scope), Q-21 (no shell in this run).
