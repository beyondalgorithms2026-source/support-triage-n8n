# Current handoff
Task: T4-13 (G13) Security findings table and eval report. Attempt 1 (overnight, unattended).
Branch: main
Last commit: 6380e7f T4-12: correct OWASP LLM Top 10 ids to the official 2025 list (Q-9) (before this goal; the loop
commits G13)
Done: `python3 -m src.score.report --run-id test-local-20261013T040225Z-0814c13 --attack-run-id
attack-local-20261013T042634Z-c7595e4` wrote `evals/eval_report.json`, `evals/SHA256SUMS`,
`evals/security_findings.{json,md}` (20 rows, OWASP column). `evals/findings.md` has the HARNESS_SPEC §6 headings; every
number is in `eval_report.json`. `src/score/report.py`: OWASP column, G11 `tickets`/`reason` fields, per-SEC residual
map, `security` summary, τ and targets in the report. One new test in `tests/test_score.py`. Q-37 records the choices.
Next task: G14 (T4-14) Buyer README.
Read first: `evals/findings.md` (Headline), `evals/eval_report.json` (G14 numbers must be in it), OPEN_QUESTIONS Q-37.
Do not change: `evals/runs/*`; τ in `0. Config`; frozen headers; node names; workflow ids; scripts/. Regenerate
`evals/eval_report.json` only with `python3 -m src.score.report` (then `--verify`).
Tests run / result: `python3 -m unittest discover -s tests -t .` → 242 OK; `compileall` clean;
`bash scripts/accept.sh G13` → ACCEPT PASS; `bash scripts/guard.sh` → guard clean. No live model calls.
Open questions: Q-37 (new). Global τ beat per-class τ on test (Q-37 (4)); ADR-001 needs an owner look.
"Trace notes (owner)" in `evals/findings.md` is a placeholder for the owner.
