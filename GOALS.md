# GOALS — T4 build plan

One goal = one Claude Code session = one local commit `T4-0X: <goal title>`. Goal `Gn` is task `T4-0n` in
`.ai/STATUS.md`. Order is dependency order: harness and golden set (G1–G6) come before the workflow (G7–G8);
a thin end-to-end slice works at G7 (middle goal); runbook, findings table, eval report and README are last.

Machine-read lines (do not reformat): `## Gn — title`, `Task:`, `Depends-on:`, `Accept:`, `Hours:`.
The acceptance script is `scripts/accept.sh`; each goal's case there is the contract. A goal is done only when
`bash scripts/accept.sh Gn` exits 0 **and** `bash scripts/guard.sh` exits 0.

Totals: 14 goals, **43 h** of human-paced work (≈ 5 days at 8–9 h/day). Live model spend for all runs ≈ $0.10–0.30
(estimate), hard-capped by `PROJECT_LLM_USD_CAP` = $2.00.

---

## G1 — Harness skeleton, normalisers, static checks
Task: T4-01
Depends-on: none
Hours: 2
Objective: Python package skeleton, the key functions every later goal uses, and the workflow static checker ported
from T2.
Files: `src/__init__.py`, `src/common/__init__.py`, `src/common/norm.py`, `src/checks/__init__.py`,
`src/checks/static_checks.py`, `tests/__init__.py`, `tests/test_norm.py`, `tests/test_static_checks.py`.
- `norm.py`: `text_norm` (NFKC, casefold, collapse whitespace, strip), `email_norm`, `dedupe_key(source, message_id)`
  (sha256 hex[:20]), `content_sha256(from_email, subject, body)` (ARCHITECTURE C-4, §8). Test vectors in the test file
  are the contract for the JS twin in G7.
- `static_checks.py`: port T2's file (secret patterns, onError, `maxTries ≤ 3`, httpRequest timeout), add:
  `--allowed-hosts` placeholder check (only `__SINK_BASE_URL__`, `__JIRA_BASE_URL__`, `__SLACK_BASE_URL__`,
  `https://api.openai.com`), no `$env`, Jira create node has `retryOnFail` false, and a report of every
  Jira/Slack path used.
Accept: `bash scripts/accept.sh G1` — unit tests above pass; `compileall` clean; static checker on a tiny inline bad
workflow returns non-zero in `--strict`.
Done means: tests pass; nothing under `evals/` or `workflows/` yet.

## G2 — Golden set: 200 labelled synthetic tickets
Task: T4-02
Depends-on: G1
Hours: 5
Objective: the stratified golden set with hard cases, exactly as `docs/HARNESS_SPEC.md` §1.
Files: `src/fixtures/__init__.py`, `src/fixtures/make_tickets.py`, `src/fixtures/hard_cases.json`,
`evals/gold/t4-001.json … t4-200.json`, `evals/inputs/manifest.csv`, `evals/README.md` (§ Label stats, § Label changes),
`tests/test_fixtures.py`.
- Gold written first, ticket rendered from gold (I-2); seed `20261012`; byte-identical on re-run.
- Hard cases hand-authored in `hard_cases.json` with `label_notes`. Injection targets use `example.invalid`.
- No real names of companies or people beyond obviously fictional ones; emails `example.com|org|net`; phones `555-01xx`;
  cards = published test numbers; SSN-format strings start with `9` or `000` style invalid ranges.
Accept: `bash scripts/accept.sh G2` — `make_tickets --check` regenerates into a temp dir and diffs; independent checks:
200 rows; bucket counts 104/48/16/12/12/8; split 100/100; ≥ 20 per category; every gold `synthetic: true`; every email
domain allowed; every duplicate in its original's split and after it; manifest columns frozen.
Done means: the set exists and is deterministic. The owner spot-checks 30 labels later (MORNING_REPORT).

## G3 — Scorer, threshold tuner, run checker, report generator (on STUB data)
Task: T4-03
Depends-on: G1, G2
Hours: 4.5
Objective: everything that judges a run, tested on hand-built STUB runs before any real run exists.
Files: `src/score/__init__.py`, `score.py`, `tune.py`, `check_run.py`, `report.py`, `tests/test_score.py`,
`tests/test_tune.py`, `tests/test_check_run.py`, `tests/test_replay_regression.py`, `tests/fixtures/stub_run/**` (STUB in
every file name or first line).
- `score.py`: frozen scorecard header (HARNESS_SPEC §5), 12 failure codes, per-class P/R/F1, confusion CSVs, cost per
  ticket / run / 1,000, latency p50/p95; reads sink CSVs, sandbox CSVs, `requests.jsonl`, `trace.jsonl`.
- `tune.py`: HARNESS_SPEC §3; refuses non-dev runs; `--apply` writes τ into `workflows/t4-triage.json` `0. Config`
  (no-op with a clear message if the file does not exist yet); `--verify`.
- `check_run.py --phase <slice|smoke|dev|test|attack> --latest|--run-id`: asserts the per-phase invariants used by
  G7–G11 acceptance (one terminal audit row per ticket per pass, issues per key ≤ 1, pass-B new issues = 0, no planted
  PII in outbound bodies or LLM input, ledger rows present, caps respected).
- `report.py`: `eval_report.json`, `SHA256SUMS`, `security_findings.{json,md}`, `--verify`, `--verify-findings`.
- `test_replay_regression.py`: asserts I-8 over every committed `evals/runs/test-*` and `attack-*`; passes vacuously
  (with a printed note) when none exist yet.
Accept: `bash scripts/accept.sh G3` — all four test modules pass; scorer on the STUB run writes the exact frozen header
and the STUB's known confusion matrix; `tune.py` on a STUB test-split run exits non-zero.
Done means: harness can judge a run before the workflow exists.

## G4 — PII redaction and injection scan (Python reference + JS twin)
Task: T4-04
Depends-on: G1, G2
Hours: 3
Objective: intake controls C-5, C-6, C-7 as tested code.
Files: `src/common/redact.py`, `src/common/inject.py`, `src/js/redact.js`, `src/js/inject.js`, `tests/test_redact.py`,
`tests/test_inject.py`, `tests/vectors/redact_vectors.json`, `tests/vectors/inject_vectors.json`.
- Redaction types: email, phone, Luhn-valid card, IBAN, US SSN-format, IPv4, URL with query string, sender display name;
  typed numbered placeholders; returns counts by type.
- Injection scan: port patterns from `RAG_ENTERPRISE_LANGGRAPH_APP/src/rag_enterprise_langgraph/input_security.py`
  (read-only source) + Slack mention tokens + HTML comments; base64 decode check; quote stripping + model cap.
- JS twins are plain ES2019 functions with no `require`, so they paste into n8n Code nodes; parity tests run them under
  `node` on the shared vector files.
- Scanner patterns may be tuned on **dev** injection tickets only; test-split injection tickets are measured in G11.
Accept: `bash scripts/accept.sh G4` — tests pass (node required); `python3 -m src.common.redact --audit evals/gold`
reports 0 surviving planted PII values over all 200 tickets; `python3 -m src.common.inject --audit evals/gold --split dev`
flags ≥ 6 of 8 dev injection tickets and ≤ 2 dev clean/hard tickets.
Done means: both controls work and agree across languages.

## G5 — Sink with Jira and Slack sandbox
Task: T4-05
Depends-on: G1
Hours: 3.5
Objective: the append-only evidence store and the contract-compatible sandboxes (ADR-003).
Files: `src/sink/__init__.py`, `src/sink/server.py`, `tests/test_sink.py`.
- Tables and stamps: ARCHITECTURE §6.3. Endpoints: `/append/<table>`, `/lookup/<table>?col=val`, `/ledger/sum?day=|run_id=`,
  `/ledger/count?since_s=`, `/_replay/active`, `/_replay/fault`, `/_health`; Jira and Slack routes: ARCHITECTURE §7.
- Auth per route group (X-Sink-Token / Basic / Bearer); refuses to start without all three secrets.
- Faults: `jira:503`, `jira:commit_then_504`, `jira:search_lag`, `slack:503`, `sink:jira_links:503`.
- `requests.jsonl`: method, path, status, active input, pass; JSON body kept for Jira, Slack and LLM-input mirror rows;
  **all headers dropped**.
Accept: `bash scripts/accept.sh G5` — `tests.test_sink` passes (ephemeral port, no network beyond localhost).
Done means: every fault and every 403 path is tested.

## G6 — Replay runner
Task: T4-06
Depends-on: G3, G5
Hours: 4
Objective: setup / run / replay against local n8n, ported from T2's `LocalN8n` (docker exec CLI import, publish,
unpublish; executions read from SQLite read-only).
Files: `src/replay/__init__.py`, `src/replay/run.py`, `tests/test_replay.py`.
- `setup`: build credentials `t4-llm`, `t4-webhook-auth`, `t4-sink-auth`, `t4-jira`, `t4-slack` in memory from `.env`,
  import via `docker exec -i n8n n8n import:credentials --input=/dev/stdin`; never print or write them.
- `run --phase P [--split dev|test] [--ids …] [--limit N] [--passes A|AB] [--force-fault id:target:mode]
  [--config-override key=value]`: placeholder substitution in memory, publish in `try`, unpublish in `finally`, fresh
  sink dir per run, sequential submit (I-7), trace from execution data (H6 input copied to a scrubbed `llm_input`
  record for leak checks, headers dropped), `summary.json`, one `cost_ledger.csv` row.
- Caps: refuse to start if `PROJECT_LLM_USD_CAP` would be exceeded by `RUN_USD_CAP`; stop submitting when the run
  passes `RUN_USD_CAP`; `n8n_version` read from the container, not a constant (fixes T2 R-9).
Accept: `bash scripts/accept.sh G6` — `tests.test_replay` passes with a fake n8n and fake docker (no network, no
model calls); `python3 -m src.replay.run --help` exits 0.
Done means: one command replays any subset of tickets and leaves complete evidence.

## G7 — Thin end-to-end slice (live)
Task: T4-07
Depends-on: G4, G6
Hours: 4
Objective: a real ticket goes webhook → redact → classify → Jira (sandbox) → audit, with cost recorded.
Files: `workflows/t4-triage.json` (slice: W0, W1, H1, H3, H4, H6, H7, H8, fixed decision, H12, H13, H16),
`workflows/t4-error-handler.json`, `tests/test_workflow.py`, `evals/runs/slice-*/`, `OPEN_QUESTIONS.md` (Q-2 answer:
logprobs present? first-token map).
- Run: `python3 -m src.replay.run setup` then `python3 -m src.replay.run run --phase slice --split dev --limit 10
  --ids <first 10 dev clean>`. Live model calls: 10 (≈ $0.002).
- Slice decision: auto-route everything except `privacy`/`other` (no thresholds yet). Marked in Config as `slice_mode`.
Accept: `bash scripts/accept.sh G7` — static checks `--strict` clean on both workflows; `tests.test_workflow` (embedded JS
equals `src/js/*.js`; H6 body references only `model_text` and Config); `check_run --phase slice --latest`: 10 tickets,
10 terminal audit rows, ≥ 1 sandbox issue, 0 planted-PII hits, ledger and cost_ledger rows, `conf_source = logprobs`
on ≥ 8 of 10 (or Q-2 records the self-report fallback and the check uses it).
Done means: the end-to-end path works on real n8n with a real model.

## G8 — Full controls: validate, decide, idempotency, Slack, queue, error paths
Task: T4-08
Depends-on: G7
Hours: 5
Objective: complete graph per ARCHITECTURE §4 (all τ = 1.01 until G9).
Files: `workflows/t4-triage.json`, `workflows/t4-error-handler.json`, `tests/test_workflow.py`, `evals/runs/smoke-*/`.
- Adds H2, H5, H9, H10, H11, H12r/H12b, H14, H15/H15s, full Config, error rows on every branch.
- Smoke run: 12 dev tickets chosen to hit every branch (one duplicate pair, one content duplicate, one injection, one
  PII-heavy, two malformed, one privacy) + forced faults `jira:commit_then_504`, `jira:503`, `slack:503`,
  `sink:jira_links:503`; passes `AB`. Live model calls ≤ 24.
Accept: `bash scripts/accept.sh G8` — static `--strict` clean; `tests.test_workflow` (every external node has onError,
timeout, bounded retry; H12 `retryOnFail` false; Config keys complete); `check_run --phase smoke --latest`: issues per
key ≤ 1, pass-B new issues 0, injection → review, malformed → rejected, no PII leak, one terminal audit row per ticket
per pass, faults produce error rows (no silent drop).
Done means: every control in ARCHITECTURE §3 exists in the workflow and has been exercised once.

## G9 — Dev run and per-class threshold tuning
Task: T4-09
Depends-on: G8
Hours: 2
Objective: tuned per-class thresholds from the dev split only (ADR-001, I-9).
Files: `evals/runs/dev-*/`, `evals/thresholds.json`, `evals/threshold_sweep.csv`, `workflows/t4-triage.json` (Config τ).
- `run --phase dev --split dev --config-override tuning_mode=true` (100 live calls ≈ $0.02), then
  `python3 -m src.score.tune --run-id <dev run> --apply`.
Accept: `bash scripts/accept.sh G9` — `tune --verify`: source run is all-dev, Config τ = thresholds.json,
sweep has 13 kinds (8 categories incl. the two policy classes for reporting, 4 priorities, 1 global) × 12 τ values
= 156 rows; `tests.test_tune` passes.
Done means: thresholds exist, are traceable to one dev run, and are in the workflow.

## G10 — Held-out test run, replay proof, scorecard
Task: T4-10
Depends-on: G9
Hours: 2
Objective: the numbers: per-class metrics, confusion, % to human, cost, and I-8 on the test split.
Files: `evals/runs/test-*/`, `evals/scorecard.csv`, `evals/confusion_category.csv`, `evals/confusion_priority.csv`,
`evals/cost_ledger.csv`.
- `run --phase test --split test --passes AB` (≈ 100 live calls in pass A, 0 expected in pass B), then
  `python3 -m src.score.score --run-id <test run> --out evals/scorecard.csv`.
- If thresholds look wrong on test, do **not** re-tune on test: record it in OPEN_QUESTIONS and continue.
Accept: `bash scripts/accept.sh G10` — `check_run --phase test --latest` (100 tickets, pass-B new issues 0, pass-B LLM
calls 0, max issues per key 1); scorecard has 100 data rows with the frozen header; `tests.test_replay_regression`
passes; project LLM spend ≤ `PROJECT_LLM_USD_CAP`.
Done means: the scorecard is real and the no-duplicate property is proven on held-out data.

## G11 — Attack run
Task: T4-11
Depends-on: G10
Hours: 2.5
Objective: execute SEC-01 … SEC-20 (`docs/SECURITY_CONTROLS.md` §2) and record raw results.
Files: `src/replay/attacks.py`, `tests/test_attacks.py`, `evals/runs/attack-*/` (incl. `attack_results.json`).
- Uses injection, pii, malformed and duplicate tickets from both splits, the burst (SEC-12/13 with in-memory cap
  overrides), wrong-token posts (SEC-18), the static path review (SEC-19) and the secret scan (SEC-20).
Accept: `bash scripts/accept.sh G11` — `tests.test_attacks` passes; `check_run --phase attack --latest`: every ID SEC-01 …
SEC-20 has `result ∈ {defended, failed, not_run}` with evidence path (and a reason when `not_run`); SEC-20 clean.
Done means: raw security evidence exists; no prose yet.

## G12 — Runbook and limitations note
Task: T4-12
Depends-on: G10
Hours: 1.5
Objective: one-page operator runbook and a plain limitations note.
Files: `docs/RUNBOOK.md`, `docs/LIMITATIONS.md`.
- Runbook headings: Start / Stop · Daily checks · Working the review queue · When the model is down · When Jira or
  Slack is down · Cap reached · Duplicate issue found · Re-tuning thresholds · Rotating secrets · Pruning n8n executions.
- Limitations: from ARCHITECTURE §11 plus anything new from G7–G10 runs, each with its evidence path.
Accept: `bash scripts/accept.sh G12` — runbook ≤ 600 words with every heading; limitations exists with ≥ 6 bullets;
banned-word check clean.
Done means: an operator can run and stop it without reading the code.

## G13 — Security findings table and eval report
Task: T4-13
Depends-on: G11, G12
Hours: 3
Objective: the written results, generated from evidence.
Files: `evals/eval_report.json`, `evals/SHA256SUMS`, `evals/security_findings.json`, `evals/security_findings.md`,
`evals/findings.md`.
- `python3 -m src.score.report` generates JSON, SHA256SUMS and the security table (ID, attack, result, control,
  residual risk, OWASP IDs). `findings.md` follows HARNESS_SPEC §6 headings; "Trace notes (owner)" is left as a
  placeholder for the owner.
Accept: `bash scripts/accept.sh G13` — `report --verify` (regeneration equals committed files) and `--verify-findings`
(every number in findings.md exists in eval_report.json); security table has 20 rows; findings headings in order;
banned-word check clean.
Done means: every published number traces to a run file.

## G14 — Buyer README
Task: T4-14
Depends-on: G13
Hours: 1
Objective: the buyer-facing README with real results, under 200 words.
Files: `README.md`.
Accept: `bash scripts/accept.sh G14` — ≤ 200 words; no "plan only" marker; every relative link resolves; each number in
README exists in `eval_report.json`; banned-word check clean.
Done means: a Head of Support can read it in one minute and find the evidence.

---

## Hours

| Goal | h | Goal | h |
|---|---|---|---|
| G1 skeleton | 2 | G8 full controls | 5 |
| G2 golden set | 5 | G9 tuning | 2 |
| G3 scorer/tuner | 4.5 | G10 test run | 2 |
| G4 redact/scan | 3 | G11 attacks | 2.5 |
| G5 sink/sandbox | 3.5 | G12 runbook | 1.5 |
| G6 runner | 4 | G13 report | 3 |
| G7 slice | 4 | G14 README | 1 |
| | | **Total** | **43** |

## Cut (to fit 4–5 days) — not built, listed in LIMITATIONS

1. Reviewer approval webhook / approve-then-create path (queue + Slack only; reviewer acts in Jira by hand).
2. Real Jira Cloud sandbox site and real Slack workspace runs (contract sandbox only; swap documented).
3. IMAP email trigger (email mapped to the webhook shape; adapter documented, not replayed).
4. Public ticket dataset (synthetic only; no licence work).
5. Semantic duplicate detection (exact message id + exact content hash only).
6. Attachment content (no OCR / parsing / malware scan).
7. Concurrency testing of the dedupe lookup.
8. Multi-run calibration, prompt A/B tests, a second model comparison.
9. Non-English tickets.
10. Loom script and a dashboard / HTML report page.
11. Cross-family code review (morning owner step, Thin Ledger routing rule).
