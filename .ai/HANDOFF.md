# Current handoff
Task: T4-02 (G2) Golden set: 200 labelled synthetic tickets. Attempt 1 (overnight, unattended).
Branch: main
Last commit: 594da6f T4-01: Harness skeleton, normalisers, static checks (this run did not commit; the loop commits)
Done: src/fixtures/make_tickets.py (seeded generator, `--check` diffs a temp-dir rebuild against the repo);
src/fixtures/hard_cases.json (48 hard + 16 injection, hand-authored, label_notes each); evals/gold/t4-001…t4-200.json;
evals/inputs/manifest.csv; evals/README.md (§ Golden set, generated § Label stats); tests/test_fixtures.py (27 tests).
Next task: G3 (T4-03) scorer, tuner, run checker, report on STUB data. G4 and G5 are also unblocked.
Read first: OPEN_QUESTIONS.md Q-22 (malformed outcomes), Q-23 (priority mix), Q-24 (gold field choices);
evals/README.md § Label stats; one gold file per bucket (e.g. t4-001, t4-105, t4-153, t4-169, t4-181, t4-193).
Do not change: gold files by hand (edit the generator or hard_cases.json, regenerate, log in § Label changes);
src/common/norm.py preimages (gold keys depend on them); the label-stats markers in evals/README.md; scripts/.
Tests run / result: `bash scripts/accept.sh G2` → ACCEPT PASS [G2]; `bash scripts/guard.sh` → guard clean;
`python3 -m unittest discover -s tests -t .` → 57 tests OK. Ad-hoc (not committed): the RAG input_security patterns
plus Slack/HTML-comment markers flag 8/8 dev injection tickets and 0 dev clean/hard tickets; they flag 4/8 test
injection tickets (fake system line, Jira-field text, underscore file name, fake footer pass). Test split is for G11.
Open questions: Q-22, Q-23, Q-24 (all owner review; cheap to reverse until G9 runs).
