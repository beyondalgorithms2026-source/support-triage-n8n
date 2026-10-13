# Current handoff
Task: T4-12 (G12) Runbook and limitations note. Attempt 1 (overnight, unattended).
Branch: main
Last commit: e6ece8e T4-11: record owner answer on Q-35 (before this goal; the loop commits G12)
Done: `docs/RUNBOOK.md` (10 headings, 580 words, commands in fenced blocks) and `docs/LIMITATIONS.md` (25 bullets:
ARCHITECTURE §11, G7–G11 run findings, GOALS § Cut; each with an evidence path). Q-36 records the choices.
Next task: G13 (T4-13) Security findings table and eval report.
Read first: `docs/LIMITATIONS.md` (residual-risk lines for findings.md), OPEN_QUESTIONS Q-34, Q-35, Q-36;
`evals/runs/attack-local-20261013T042634Z-c7595e4/attack_results.json`.
Do not change: `evals/runs/*`; τ in `0. Config`; frozen headers; node names; workflow ids; scripts/.
Tests run / result: `bash scripts/accept.sh G12` → ACCEPT PASS; `bash scripts/guard.sh` → guard clean.
No unit tests or live runs were needed (docs only).
Open questions: Q-36 (new). Q-2, Q-4…Q-9, Q-11, Q-12, Q-14…Q-17 and Q-22…Q-34 still have no owner answer.
