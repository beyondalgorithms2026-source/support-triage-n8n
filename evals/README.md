# evals — how we judge outputs

Product evals (Thin Ledger §8), not coding ceremony. Formats are frozen in `docs/HARNESS_SPEC.md`.

## There is no gold set yet
Gold files are created by the generator in G2. Until then this folder holds only this README.
Do not add example or placeholder gold rows.

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
(G2 writes counts per bucket × category × split here.)

## Label changes
(Dated entries: input_id, old → new, reason, runs re-scored.)
