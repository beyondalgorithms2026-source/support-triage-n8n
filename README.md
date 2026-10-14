# Support Ticket Triage on n8n

By Spanfold. **All tickets are synthetic.**

For a Head of Support at a 20–200 person SaaS: each new ticket is redacted, classified (category, priority,
urgency) with a confidence score, then filed in Jira and posted to Slack, or held for a person with a reason.

## Results

Held-out test split, 100 synthetic tickets, `gpt-4o-mini` ([eval_report.json](evals/eval_report.json)):

- Category macro-F1 0.99; priority macro-F1 0.72 (P3 often called P2); P1 recall 92%
- 79% sent to a human; auto-routed precision 0.85 against a 0.95 target: both miss target
- 0 personal-data leaks, 0 duplicate Jira issues on replay
- Attacks: 19 defended, 0 failed, 1 not run
- Model cost $0.11 per 1,000 tickets

## Evidence

[Findings](evals/findings.md) · [Security table](evals/security_findings.md) ·
[Limitations](docs/LIMITATIONS.md) · [Runbook](docs/RUNBOOK.md) · [Architecture](docs/ARCHITECTURE.md)

## Limits

Synthetic data and a small sample. Pattern-based redaction. Jira and Slack checks ran against a local sandbox;
a real-workspace demo is owner-run. Not a client deployment.

MIT licence, © 2026 Spanfold.
