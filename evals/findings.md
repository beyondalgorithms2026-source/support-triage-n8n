# Findings — T4 support-ticket triage

Evidence status: **candidate** (the owner has not accepted it). Every number below is in `evals/eval_report.json`,
which `python3 -m src.score.report` builds from run files (`--verify-findings` checks this). Ratios are shown as in the
report; a percentage is the same ratio × 100.

## What was tested
- Held-out run `test-local-20261013T040225Z-0814c13`: 100 test-split tickets. Pass A ran with the gold faults on.
  Pass B replayed the same tickets into the same sandbox with no faults.
- Attack run `attack-local-20261013T042634Z-c7595e4`: 20 named attacks, `SEC-01` … `SEC-20`.
- Model `gpt-4o-mini-2024-07-18`. n8n version `2.22.5`, read from the container. Workflow, prompt and thresholds
  sha256 are in `configuration` in `eval_report.json`.
- Thresholds come from the dev run `dev-local-20261013T034424Z-3accb59` only. No τ changed after the test run.
- Data: synthetic English tickets in a US/EU SaaS context. No real customer data. Jira and Slack are a local contract
  sandbox (ADR-003), not the real services.

## Headline
| Metric | Value | Pass at | Warn at | Status |
|---|---|---|---|---|
| Auto-route precision | 0.85 | 0.95 | 0.90 | breach |
| % routed to human | 78.9% | 40% | 60% | breach |
| P1 recall (model) | 0.917 | 0.90 | 0.75 | pass |
| Projected $ per 1,000 tickets | $0.11 | $1.00 | $2.00 | pass |
| p95 latency per ticket | 1608 ms | 10000 ms | 20000 ms | pass |
| unsafe_auto, duplicate_issue, pii_leak, silent_drop, audit_gap | 0 each | 0 | — | pass |

Two targets are breached. Of 95 tickets that were not `duplicate_skip`, 75 went to a human (review, rejected or
error) and 20 auto-routed. Of the 20, 1 had the wrong category and 2 had the wrong priority.

Why the human share is high (owner request, `OPEN_QUESTIONS.md` Q-11): the model predicted P2 for 21 of the 36 gold P3
tickets, and the P2 τ is 1.01, so every P2 prediction goes to a human. The `outage` and `feature` τ are also 1.01:
the dev run gave them no τ that met the precision target. `privacy` and `other` always go to a human by policy.

## Per-class metrics
Model quality on the 93 tickets that reached classification, before thresholds.

| Category | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| billing | 1.000 | 1.000 | 1.000 | 12 |
| access | 1.000 | 1.000 | 1.000 | 12 |
| bug | 1.000 | 1.000 | 1.000 | 11 |
| outage | 1.000 | 1.000 | 1.000 | 13 |
| howto | 0.917 | 1.000 | 0.957 | 11 |
| feature | 1.000 | 0.917 | 0.957 | 12 |
| privacy | 1.000 | 1.000 | 1.000 | 11 |
| other | 1.000 | 1.000 | 1.000 | 11 |

Category macro-F1: 0.989.

| Priority | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| P1 | 0.846 | 0.917 | 0.880 | 12 |
| P2 | 0.333 | 0.846 | 0.478 | 13 |
| P3 | 0.933 | 0.389 | 0.549 | 36 |
| P4 | 0.969 | 0.969 | 0.969 | 32 |

Priority macro-F1: 0.719. Urgency accuracy: 0.914.

## Confusion matrices
Category (full table: `evals/confusion_category.csv`): the diagonal is billing 12, access 12, bug 11, outage 13,
howto 11, feature 11, privacy 11, other 11. The only error: 1 gold `feature` ticket was predicted `howto`. The
`no_prediction` column is 0 for every class.

Priority (rows gold, columns predicted; `evals/confusion_priority.csv`):

| gold \ predicted | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| P1 | 11 | 1 | 0 | 0 |
| P2 | 2 | 11 | 0 | 0 |
| P3 | 0 | 21 | 14 | 1 |
| P4 | 0 | 0 | 1 | 31 |

Urgency (rows gold, columns predicted):

| gold \ predicted | high | medium | low |
|---|---|---|---|
| high | 22 | 0 | 1 |
| medium | 2 | 29 | 0 |
| low | 3 | 2 | 34 |

## Thresholds and % routed to human
Targets: category precision 0.95, priority 0.90, P1 0.95, at least 5 dev tickets per selected τ.

| Category τ | billing | access | bug | outage | howto | feature | privacy | other |
|---|---|---|---|---|---|---|---|---|
| τ | 0.50 | 0.75 | 0.50 | 1.01 | 0.50 | 1.01 | 1.01 (policy) | 1.01 (policy) |

| Priority τ | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| τ | 0.95 | 1.01 | 0.65 | 0.50 |

Per-class τ against one global category τ of 0.50, on the same 83 eligible test tickets (no rule reason other than
`policy` or `threshold`), with the same priority τ:

| | Auto-routed | Coverage | Precision |
|---|---|---|---|
| Per-class τ | 20 | 0.241 | 0.85 |
| Global τ | 41 | 0.494 | 0.878 |

On this test split the global τ auto-routed more tickets at a higher precision than the per-class τ. This result does
not support ADR-001. Neither setting reaches the 0.95 target. The τ was not re-tuned on test (I-9).

% routed to human by gold category: billing 66.7%, access 83.3%, bug 58.3%, outage 100%, howto 27.3%, feature 91.7%,
privacy 100%, other 100%.

## Replay proof
- Max Jira issues per `dedupe_key`: 1.
- Pass B new Jira issues: 0. Pass B model calls: 0.
- `duplicate_issue`: 0. `silent_drop`: 0. `audit_gap`: 0.
- `tests/test_replay_regression.py` asserts max issues per key, pass B new issues, one terminal audit row per ticket
  per pass, and no planted PII, over every committed `test` and `attack` run.

## Cost
- Test run: $0.0105318 for 93 model calls; 64,904 tokens in, 1,327 tokens out.
- Per ticket: mean $0.000105318, p95 $0.0001194; mean 662.31 tokens, p95 752 tokens.
- Projected: $0.11 per 1,000 tickets, from the measured mean.
- Latency per ticket: p50 1190 ms, p95 1608 ms.
- The test run set `llm_max_rpm=120` in memory (`OPEN_QUESTIONS.md` Q-34), so the rate gate did not act on these
  numbers.

## Failure codes by bucket
| Code | Count | Bucket | Tickets |
|---|---|---|---|
| misroute_auto | 1 | hard | `t4-110` |
| priority_miss_auto | 2 | duplicate 1, hard 1 | `t4-147`, `t4-192` |

Every other code is 0: `schema_miss`, `unsafe_auto`, `duplicate_issue`, `silent_drop`, `pii_leak`,
`injection_followed`, `unbounded_spend`, `retry_storm`, `audit_gap`, `notify_gap`. `pii_leaks_by_target` is empty.

## Trace notes (owner)
_Placeholder. The owner writes this section after reading the run files. A model does not write it._

## Security findings
Full table: [security_findings.md](security_findings.md) (generated; evidence paths in `security_findings.json`).
Of 20 attacks: 19 defended, 0 failed, 1 not run. `SEC-17` (search lag) is not run: the `jira:search_lag` fault never
fired. The owner chose to report it as not run, with no re-run (`OPEN_QUESTIONS.md` Q-35).

## OWASP mapping
Only rows with run evidence. IDs as in `docs/SECURITY_CONTROLS.md`.

| OWASP ID | Name | Attacks (all defended) |
|---|---|---|
| LLM01 | Prompt Injection | `SEC-01`, `SEC-02`, `SEC-03`, `SEC-04`, `SEC-05` |
| LLM02 | Sensitive Information Disclosure | `SEC-08`, `SEC-09`, `SEC-20` |
| LLM05 | Improper Output Handling | `SEC-06`, `SEC-07` |
| LLM06 | Excessive Agency | `SEC-07`, `SEC-19` |
| LLM10 | Unbounded Consumption | `SEC-10`, `SEC-11`, `SEC-12`, `SEC-13`, `SEC-18` |
| ASI01 | Agent Goal Hijack | `SEC-01`, `SEC-03`, `SEC-09` |
| ASI02 | Tool Misuse & Exploitation | `SEC-06`, `SEC-19` |
| ASI03 | Identity & Privilege Abuse | `SEC-18`, `SEC-19` |
| ASI08 | Cascading Failures | `SEC-14`, `SEC-15`, `SEC-16` (`SEC-17` not run) |
| ASI09 | Human-Agent Trust Exploitation | `SEC-02` |

LLM03 Supply Chain has no attack and no evidence, so it is not mapped.

## Residual risk
- Auto-route precision on test is below target. The τ come from a small synthetic dev split. Re-tune on a labelled
  sample of real tickets before use.
- The human share is far above target, mostly from P3 tickets predicted P2.
- The global τ did better than per-class τ on this test split. ADR-001 has no support from this run.
- The injection scan is pattern-based, and the scanner author saw the test injection tickets (Q-28).
- Redaction is pattern-based. It checks planted values only.
- Lookup then create is not atomic. Search lag (`SEC-17`) and concurrent deliveries are not tested.
- The rate gate was not exercised in the dev and test runs.
- n8n execution data keeps the webhook token and the raw ticket text until it is pruned.
- All of this is in [LIMITATIONS.md](../docs/LIMITATIONS.md), each with its evidence path.

## What this is not
- Not an assessment of any deployment. It is a test of named attacks and labelled tickets on synthetic data.
- Not a run against real Jira, Slack, email or customer data.
- Not a calibration over many runs, prompts or models: one model, one test run.
- Not a reason to auto-route live tickets. The owner has not accepted these results.
