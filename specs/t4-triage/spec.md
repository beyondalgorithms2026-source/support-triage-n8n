# Spec — T4 Support Ticket Triage & Routing

## Outcome
A replayable n8n triage workflow plus its evidence: a Head of Support can see, on 200 labelled synthetic tickets,
how accurately tickets are classified per class, what share goes to a human at tuned per-class thresholds, that
replays never create duplicate Jira issues, that PII does not reach the model or Jira/Slack, what each ticket costs,
and which named attacks the controls stopped.

## Users
- **Buyer**: Head of Support / CS, 20–200 person US/EU SaaS. Reads README + findings + runbook.
- **Operator**: runs the replay, works the review queue, re-tunes thresholds (RUNBOOK).

## In scope
Webhook intake (email mapped to the same shape) · PII redaction · injection scan · schema-bound classification with
logprob confidence · rule validation · per-class thresholds · idempotent Jira create (sandbox) · Slack notify
(sandbox) · review queue · audit + cost ledger · golden set (200) · metrics, confusion, threshold sweep · replay
proof · 20 attacks · runbook · 7 ADRs · findings + eval report · buyer README.

## Out of scope
See `GOALS.md` § Cut and `docs/SECURITY_CONTROLS.md` §3.

## Frozen contracts (architecture session only)
Gold format, manifest, scorecard, cost ledger, failure taxonomy (`docs/HARNESS_SPEC.md`); dedupe keys and Jira/Slack
contract (`docs/ARCHITECTURE.md` §7–§8); credential names; enum labels (§6.2).

## Acceptance (project-level)
- [ ] `evals/scorecard.csv`: 100 test-split rows from one real run_id; thresholds from one dev run_id.
- [ ] Every `dedupe_key` has ≤ 1 sandbox Jira issue across all runs; pass-B replay creates 0 issues and 0 model calls.
- [ ] `pii_leak`, `silent_drop`, `audit_gap`, `unsafe_auto`, `duplicate_issue` = 0 on the test run, or each instance
      is reported as a finding with its input_id.
- [ ] `static_checks --strict` clean on both workflow files.
- [ ] SEC-01…SEC-20 each have a recorded result and evidence path.
- [ ] Every number in findings and README is in `evals/eval_report.json` (generated).
- [ ] Docs carry residual risk and none of the banned words (AGENTS.md).
- [ ] Fresh clone + `.env` + README/RUNBOOK steps reproduce a run on local Docker n8n 2.22.5 (numbers may differ).
