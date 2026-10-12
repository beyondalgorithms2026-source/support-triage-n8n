# Decisions

Cap for this project: 7 ADRs. One file per ADR in `docs/adr/`. Cheaper-to-reverse choices live in
`docs/ARCHITECTURE.md` and `OPEN_QUESTIONS.md`. Format per Thin Ledger §5 (Status, Date, Decision, Reason,
Consequences). Acceptance is recorded here by the owner, dated, as in T2.

| ADR | Title | Status |
|---|---|---|
| [ADR-001](adr/ADR-001-per-class-thresholds.md) | Per-class confidence thresholds, not one global threshold | Proposed |
| [ADR-002](adr/ADR-002-human-queue-is-designed-outcome.md) | The human review queue is a designed outcome, not an error | Proposed |
| [ADR-003](adr/ADR-003-jira-sandbox.md) | Jira and Slack are a local, contract-compatible sandbox | Proposed |
| [ADR-004](adr/ADR-004-redaction-before-model.md) | Redact PII before the model and before every outbound write | Proposed |
| [ADR-005](adr/ADR-005-model-selection.md) | gpt-4o-mini-2024-07-18 with logprob confidence; fallback is the human queue | Proposed |
| [ADR-006](adr/ADR-006-idempotent-jira-writes.md) | Idempotent Jira writes: two keys, Jira label, reconcile before retry | Proposed |
| [ADR-007](adr/ADR-007-spend-cap-by-day.md) | Spend and rate caps before the call, keyed by UTC day and run | Proposed |

Owner acceptance:
