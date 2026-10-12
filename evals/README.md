# evals — how we judge outputs

Product evals (Thin Ledger §8), not coding ceremony. Formats are frozen in `docs/HARNESS_SPEC.md`.

## Golden set
`gold/t4-001.json … t4-200.json` and `inputs/manifest.csv` are written by `python3 -m src.fixtures.make_tickets`
(seed `20261012`). `python3 -m src.fixtures.make_tickets --check` regenerates them in a temp dir and fails on any
byte difference. Do not edit gold files by hand: change the generator or `src/fixtures/hard_cases.json`, regenerate,
and add a line under § Label changes.

## Where gold comes from
Each `gold/<input_id>.json` is written **first**; the ticket text is rendered from it. Gold is never produced by, or
corrected toward, a model's output. If a ticket reads ambiguously, fix the generator (or move it to `hard` with the
argument in `label_notes`), not the gold.

## Splits
`dev` (100) is for tuning prompts, rules, scanner patterns and thresholds. `test` (100) is scored once per workflow
version. Never tune on `test`. If a test result looks wrong, write it in `OPEN_QUESTIONS.md`; do not re-tune.

## What is judged
1. Model quality: per-class precision / recall / F1 and confusion matrices (category, priority, urgency).
2. Routing: % auto-routed, % routed to human, auto-route precision, per-class vs global thresholds.
3. 12 failure codes (`docs/HARNESS_SPEC.md` §5), each a deterministic check on sink, sandbox, request log and
   execution data. No LLM judge.
4. Replay proof: pass B adds zero Jira issues and makes zero model calls.
5. Security: SEC-01…SEC-20 with result and evidence.
6. Cost: tokens and $ per ticket, per run, per 1,000 tickets (measured).

## Top-down vs bottom-up
- Top-down (frozen at G3): the 12 codes and the metrics above.
- Bottom-up (owner, after the test run): read at least 15 traces across all buckets and write § Trace notes in
  `findings.md`. A pattern that is not one of the 12 codes goes into notes and `OPEN_QUESTIONS.md`.

## Rules
- Numbers in findings must trace to `runs/` or a generated file (`eval_report.json`, `scorecard.csv`).
- Model errors that the workflow routes to review are reported as model misses, not hidden.
- Stub data for tests lives in `tests/fixtures/`, never here.

## Label stats
<!-- label-stats:start (written by src/fixtures/make_tickets.py; do not edit by hand) -->

Cells are dev / test counts.

| bucket | billing | access | bug | outage | howto | feature | privacy | other | total |
|---|---|---|---|---|---|---|---|---|---|
| clean | 7 / 6 | 6 / 7 | 7 / 6 | 6 / 7 | 7 / 6 | 6 / 7 | 7 / 6 | 6 / 7 | 52 / 52 |
| hard | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 24 / 24 |
| injection | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 8 / 8 |
| pii | 2 / 1 | 1 / 1 | 1 / 1 | 0 / 1 | 0 / 1 | 1 / 0 | 0 / 1 | 1 / 0 | 6 / 6 |
| duplicate | 1 / 1 | 0 / 0 | 1 / 0 | 2 / 0 | 2 / 2 | 0 / 3 | 0 / 0 | 0 / 0 | 6 / 6 |
| malformed | 1 / 0 | 1 / 0 | 0 / 1 | 0 / 1 | 1 / 0 | 0 / 1 | 1 / 0 | 0 / 1 | 4 / 4 |
| all | 15 / 12 | 12 / 12 | 13 / 12 | 12 / 13 | 14 / 13 | 11 / 15 | 12 / 11 | 11 / 12 | 100 / 100 |

| label | value | dev | test | total |
|---|---|---|---|---|
| priority | P1 | 11 | 12 | 23 |
| priority | P2 | 16 | 13 | 29 |
| priority | P3 | 38 | 38 | 76 |
| priority | P4 | 35 | 37 | 72 |
| urgency | high | 29 | 23 | 52 |
| urgency | medium | 37 | 33 | 70 |
| urgency | low | 34 | 44 | 78 |
| expect_outcome | auto_route | 63 | 65 | 128 |
| expect_outcome | review | 28 | 28 | 56 |
| expect_outcome | duplicate_skip | 5 | 5 | 10 |
| expect_outcome | rejected | 4 | 2 | 6 |
| hard_case | ambiguous | 4 | 5 | 9 |
| hard_case | multi_issue | 4 | 5 | 9 |
| hard_case | tone_mismatch | 7 | 3 | 10 |
| hard_case | short | 3 | 5 | 8 |
| hard_case | thread_quoted | 4 | 4 | 8 |
| hard_case | auto_reply | 2 | 2 | 4 |
| fault (test, pass A) | jira:503 | 0 | 2 | 2 |
| fault (test, pass A) | jira:commit_then_504 | 0 | 3 | 3 |
| fault (test, pass A) | jira:search_lag | 0 | 1 | 1 |
| fault (test, pass A) | sink:jira_links:503 | 0 | 2 | 2 |
| fault (test, pass A) | slack:503 | 0 | 2 | 2 |

<!-- label-stats:end -->

## Label changes
(Dated entries: input_id, old → new, reason, runs re-scored.)
