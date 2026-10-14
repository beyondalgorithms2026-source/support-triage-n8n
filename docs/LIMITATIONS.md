# Limitations

What this build does not do, or did not test. Each item names its evidence. Sources: `docs/ARCHITECTURE.md` §11,
the G7–G11 runs in `evals/runs/`, `OPEN_QUESTIONS.md`, and `GOALS.md` § Cut. Residual risk is in each line.

Run folders cited: `slice-local-20261012T225612Z-98461ef`, `smoke-local-20261013T032636Z-88604b7`,
`dev-local-20261013T034424Z-3accb59`, `test-local-20261013T040225Z-0814c13`, `attack-local-20261013T042634Z-c7595e4`
(all under `evals/runs/`).

## Design limits (ARCHITECTURE §11)
- An injection that reads as a normal ticket and pushes a plausible label passes every rule. C-6 is a pattern scan,
  not a classifier. The only defence is: no tools, three enum fields, deterministic Jira and Slack text.
  Evidence: `docs/ARCHITECTURE.md` §11; SEC-01…SEC-07 in `attack-…/attack_results.json` cover tickets the scan hit.
- The scanner's test-split result is not blind: the G4 worker saw the test injection tickets while it wrote the
  patterns. Evidence: `OPEN_QUESTIONS.md` Q-28 (2).
- Redaction is pattern-based. Free-text names other than the sender, street addresses and order numbers stay in the
  text. `pii_leak` measures planted values only. Evidence: SEC-08 in `attack-…/attack_results.json`; Q-8.
- Lookup-then-create is not atomic. Replay is sequential (I-7), so two deliveries at the same time were never sent.
  Evidence: `docs/ARCHITECTURE.md` §8; `GOALS.md` § Cut 7.
- Jira search lag is not tested. SEC-17 is `not_run`: the `jira:search_lag` fault never fired. Evidence: SEC-17 in
  `attack-…/attack_results.json`; Q-35 owner answer.
- Thresholds come from 100 synthetic dev tickets: small samples per class, synthetic language. Expect drift on real
  tickets. Re-tune on a labelled sample of real tickets before use. Evidence: `evals/thresholds.json`
  (`source_run_id`), `evals/threshold_sweep.csv`.
- One model, one run, temperature 0. No repeated-run calibration. The thresholds hold for `gpt-4o-mini-2024-07-18`
  only. Evidence: `test-…/summary.json` (`model`); `docs/adr/ADR-005-model-selection.md`.
- n8n execution data holds the webhook token and the ticket text before redaction until it is pruned.
  Evidence: `docs/ARCHITECTURE.md` §11 (T2 R-3); `docs/RUNBOOK.md` § Pruning n8n executions.

## Found in the G7–G11 runs
- `outage`, `feature` and `P2` reach no precision target, so their τ is 1.01: always human. Evidence:
  `evals/thresholds.json`; `evals/threshold_sweep.csv`; Q-33 (5).
- Most test tickets end in review. The model predicts P2 for many gold P3 tickets, and P2 is always human. The human
  share is far above the HARNESS_SPEC §2 target. Evidence: `test-…/sink/audit.csv`; `evals/confusion_priority.csv`;
  Q-34 (3).
- The rate gate was not exercised in dev or test: both runs set `llm_max_rpm=120` in memory. The runner does not pace
  tickets, and the test peak passed the committed value. Only the SEC-12 and SEC-13 segments ran at the committed
  value. Evidence: `test-…/summary.json` (`config_overrides`); `attack-…/segments/sec12/summary.json`; Q-33 (2), Q-34 (2).
- The sink writes control characters raw into CSV. Gold t4-198 puts a NUL into `review_queue.csv`; the Python csv
  module fails on it. A sink restart on that folder was not tested. Evidence: `test-…/sink/review_queue.csv`; Q-34 (4).
- A lost link row ends `error` with an `issue_key` and no queue row. Recovery depends on the next delivery finding
  the Jira label. Evidence: SEC-16 in `attack-…/attack_results.json`; Q-32 (3), Q-34 (1).
- Error-handler rows carry no `run_id` (the error trigger has no webhook headers). Evidence: Q-31 (6);
  `workflows/t4-error-handler.json`.
- On n8n 2.22.5, `$('X').first()` without a branch index read an empty error branch. The workflow uses `first(0)`, and
  a test blocks a bare `first()`; a new node that skips the rule brings the bug back. Evidence:
  `smoke-local-20261013T032636Z-88604b7/sink/audit.csv`; Q-32 (7).
- Sandbox status codes differ from the real APIs: a wrong credential gives 403 here, 401 in real Jira, and HTTP 200
  `ok:false` in real Slack. Error branches were tested against the sandbox only. Evidence: Q-29 (1); ADR-003.
- The `|` join in `content_sha256` is ambiguous when a field holds `|`. Evidence: Q-19 (5); `src/common/norm.py`.
- Each publish and unpublish restarts the shared `n8n` container, which also holds T2's workflows. Evidence:
  `src/replay/run.py` (`LocalN8n.publish`); Q-15.

- Auto-routed precision on test is 0.85; the target is 0.95. Evidence: `evals/eval_report.json` `metric_status`.
- A single global category τ simulated on the committed runs cuts the human share (test 78% → 56%) at equal or
  better precision. It is not adopted: it needs a dev re-tune and a test re-run. Evidence: close plan §2.3.

## Not built (GOALS § Cut)
- No reviewer approval webhook. A reviewer acts in Jira by hand.
- All evaluated numbers come from the local Jira and Slack sandbox. An owner-run demo mode (`--real`, ≤ 3 tickets)
  exists for a real Jira Cloud site and Slack workspace; it is a demo, not an evaluation. Evidence: close plan §4.
- Jira Cloud Free has no custom permission schemes, so the demo bot cannot be limited to create-only. Mitigation is
  a demo-only project and a short-lived token. Evidence: close plan §4.3.
- The IMAP email adapter is documented, not replayed.
- Synthetic English tickets only: no public dataset, no other language.
- No semantic duplicate detection: exact message id and exact content hash only.
- No attachment content: no OCR, no parsing, no malware scan.
- No prompt A/B test and no second model comparison.

Evidence for this section: `GOALS.md` § Cut.
