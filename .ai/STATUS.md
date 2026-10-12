# Status

Task IDs are `T4-NN` (goal `Gn` in `GOALS.md`). Never use bare T1–T9: those are T2's task ids.
The table between the markers is written only by `scripts/status.py` (overnight loop or owner). States:
TODO · IN_PROGRESS · DONE · BLOCKED (3 failed acceptance attempts; error in Evidence) · SKIPPED (a dependency is
blocked). A DONE row is never reopened by the loop.

| Milestone | State | Evidence |
|---|---|---|
| M0 Plan + harness spec (T4-00) | Done, awaiting owner acceptance of ADR-001…007 and frozen formats | architecture session 2026-10-12; `bash scripts/accept.sh plan` |
| M1 Harness + golden set (T4-01…T4-06) | Not started | — |
| M2 Thin slice + full workflow (T4-07, T4-08) | Not started | — |
| M3 Tuning, test run, attacks (T4-09…T4-11) | Not started | — |
| M4 Runbook, findings, eval report, README (T4-12…T4-14) | Not started | — |
| Public link | Owner gate, out of scope for agents | — |

<!-- status-table:start -->
| Task | Goal | Title | State | Attempts | Evidence |
|---|---|---|---|---|---|
| T4-01 | G1 | Harness skeleton, normalisers, static checks | DONE | 1 | accept+guard pass (attempt 1, $1.4715254) |
| T4-02 | G2 | Golden set: 200 labelled synthetic tickets | DONE | 1 | accept+guard pass (attempt 1, $5.6587796) |
| T4-03 | G3 | Scorer, threshold tuner, run checker, report generator (on STUB data) | TODO | 0 | — |
| T4-04 | G4 | PII redaction and injection scan (Python reference + JS twin) | TODO | 0 | — |
| T4-05 | G5 | Sink with Jira and Slack sandbox | TODO | 0 | — |
| T4-06 | G6 | Replay runner | TODO | 0 | — |
| T4-07 | G7 | Thin end-to-end slice (live) | TODO | 0 | — |
| T4-08 | G8 | Full controls: validate, decide, idempotency, Slack, queue, error paths | TODO | 0 | — |
| T4-09 | G9 | Dev run and per-class threshold tuning | TODO | 0 | — |
| T4-10 | G10 | Held-out test run, replay proof, scorecard | TODO | 0 | — |
| T4-11 | G11 | Attack run | TODO | 0 | — |
| T4-12 | G12 | Runbook and limitations note | TODO | 0 | — |
| T4-13 | G13 | Security findings table and eval report | TODO | 0 | — |
| T4-14 | G14 | Buyer README | TODO | 0 | — |
<!-- status-table:end -->

Target: local Docker `n8nio/n8n:2.22.5` (container `n8n`, shared with T2). Sink/sandbox port 8790.
Model: `gpt-4o-mini-2024-07-18` (ADR-005; logprob check pending, OPEN_QUESTIONS Q-2).

Last updated: 2026-10-12 18:28 UTC (scripts/status.py)
