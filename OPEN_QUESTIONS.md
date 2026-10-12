# Open questions — decisions made, ranked by cost to reverse

Replaces T2's `.ai/QUESTIONS.md` for T4. Each entry: the decision taken so work can continue, why, what reversing it
costs. Owner: answer inline with a date (`Owner answer (YYYY-MM-DD):`). Overnight workers add new entries at the
bottom under § Overnight decisions, dated, with the same fields; they never stop to ask.

Cost scale: **H** = redo labels + all runs + findings · **M** = rework one or two goals · **L** = config or doc edit.

## Q-1 Synthetic-only golden set (no public dataset) — H
Decision: 200 synthetic English tickets generated from gold (HARNESS_SPEC §1). No public dataset in this build.
Why: no licence work; full control of hard cases, PII and injections; T2 precedent. Public support datasets I know of
carry non-commercial licences that do not fit a sales portfolio (not re-checked here).
Reverse: new data, new labels, new dev/test runs, new thresholds, rewrite findings.
Owner answer (2026-10-12, in chat): accept — synthetic-only English tickets.

## Q-2 Confidence from token logprobs on gpt-4o-mini — H
Decision: per-class confidence = renormalised first-token probability of the chosen enum value (ADR-005). Assumes the
OpenAI chat API returns `logprobs` together with strict `json_schema` output for `gpt-4o-mini-2024-07-18`. Not yet
verified on this account: G7 verifies on 10 live calls and records the result and the first-token map here.
If logprobs are missing: fall back to a self-reported confidence field (adds one schema field), expect more review.
Reverse: schema + parser + all thresholds and runs.
Owner answer:

## Q-3 Taxonomy: 8 categories, P1–P4 priority, 3-level urgency — H
Decision: `billing, access, bug, outage, howto, feature, privacy, other`; priority `critical/high/normal/low` =
P1–P4; urgency `high/medium/low`; definitions and tie-breaks in HARNESS_SPEC §1.2. Priority is classified directly,
with cross-check rules (R1–R3) rather than derived from an impact × urgency matrix.
Why: covers typical SaaS support queues; 8 classes keep ≥ 20 tickets per class in 200.
Reverse: relabel, re-prompt, re-tune, re-run.
Owner answer (2026-10-12, in chat): accept as proposed (8 categories, P1–P4, 3 urgency levels).

## Q-4 Split 100 dev / 100 test, stratified — M
Decision: tune on dev only (I-9). ≈ 12 tickets per class per split: thresholds are noisy (stated in findings).
Reverse: regenerate split, rerun dev + test.
Owner answer:

## Q-5 Jira and Slack are a local contract sandbox, not real Atlassian/Slack — M
Decision: ADR-003. Real Jira Cloud free site + real Slack workspace is a documented swap, not run.
Why: unattended build, no accounts or tokens, fault injection for the lost-response case.
Reverse: create site/workspace, bot users, credentials; one live run; add real-API differences to findings.
Owner answer:

## Q-6 HTTP Request nodes instead of n8n's Jira / Slack nodes — M
Decision: raw REST v3 / Web API calls, so the contract and the least-privilege surface are visible and sandboxable.
Reverse: swap nodes, re-run smoke and test.
Owner answer:

## Q-7 Idempotency keys = message id hash + content hash, Jira label as second source — M
Decision: ADR-006. No semantic duplicate detection.
Reverse: key change → re-run all runs that prove I-8.
Owner answer:

## Q-8 Redaction pattern set and placeholder format — M
Decision: email, phone, Luhn card, IBAN, US SSN-format, IPv4, URL-with-query, sender display name → `[TYPE_n]`.
Free-text names / addresses not covered (residual risk).
Reverse: change JS + Python twins + vectors, re-run.
Owner answer:

## Q-9 OWASP 2026 numbering from secondary sources — L
Decision: LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Excessive Agency, LLM04 Supply Chain,
LLM06 Unbounded Consumption, LLM10 Improper Output Handling (matches the owner's T2 Q-4 answer); Agentic ASI01, ASI02,
ASI03, ASI08, ASI09 (Dec 2025 list). Confirm against the official OWASP GenAI pages before publishing.
Reverse: doc edit.
Owner answer:

## Q-10 Precision targets and policy classes — L
Decision: category auto-route precision target 0.95; priority 0.90 (P1 0.95); min 5 dev tickets per selected bin;
`privacy` and `other` always go to review. Unachievable class → τ = 1.01 (always human).
Reverse: change targets, re-run `tune.py` on the same dev run, re-run test.
Owner answer (2026-10-12, in chat): as proposed — category 0.95, priority 0.90 (P1 0.95); privacy + other always human.

## Q-11 Pass / warn / breach targets for the report — L
Decision: HARNESS_SPEC §2 table (auto-route precision ≥ 0.95, % to human ≤ 40%, zero-tolerance codes = 0,
P1 recall ≥ 0.90, ≤ $1 per 1,000 tickets, p95 ≤ 10 s).
Reverse: edit table, regenerate report.
Owner answer:

## Q-12 Model spend caps — L
Decision: `RUN_USD_CAP` $0.25 (T2 owner override), `DAILY_USD_CAP` $1.00, `PROJECT_LLM_USD_CAP` $2.00, 30 calls/min.
Expected real spend for all T4 runs ≈ $0.10–0.30.
Reverse: edit `.env` + `0. Config`.
Owner answer:

## Q-13 Overnight Claude budgets and hard stop — L
Decision: `--max-budget-usd` $12 per goal, $100 total, hard stop 08:00 IST, 90 min wall per goal, 3 attempts,
30-min limit retry. On a subscription the USD figures are API-equivalent and act as a runaway brake.
Reverse: edit `overnight.conf`.
Owner answer (2026-10-12, in chat): $12 per goal, $100 total, hard stop 08:00 IST.

## Q-14 Layout deviations from T2 — L
Decision: root `HANDOFF.md` (static start-here) **plus** `.ai/HANDOFF.md` (rolling, T2); `OPEN_QUESTIONS.md` replaces
`.ai/QUESTIONS.md`; `GOALS.md` replaces `specs/*/plan.md` + `tasks.md` (spec.md kept); ADRs as files in `docs/adr/`
with `docs/DECISIONS.md` as index; ADR cap 7 (T2: 2); STATUS gains a machine-written task table.
Why: the brief names these files; the overnight loop needs one machine-readable plan.
Reverse: move files.
Owner answer:

## Q-15 Shared n8n container and port — L
Decision: reuse container `n8n` (2.22.5) that holds T2's (inactive) workflows; T4 names prefixed `t4-`; sink port 8790.
`~/Projects/n8n-local/docker-compose.yml` still says `n8nio/n8n:latest` — not changed (outside this folder); pin it
yourself if you ever recreate the container from that file.
Owner answer:

## Q-16 Overnight worker = Claude for every goal — L
Decision: `opus` with `sonnet` fallback, effort high, all 14 goals. Breaks the Thin Ledger routing mix for one night
and makes author and checker the same family; morning step: cross-family review of G7, G8, G13.
Owner answer:

## Q-17 Banned words list — L
Decision: the brief's four words plus T2's fifth (the list lives only in `AGENTS.md` § Rules); enforced by
`scripts/checks.py banned` on every prose file except AGENTS.md and CLAUDE.md.
Owner answer:

## Q-18 `git init` is an owner step — L (blocks the overnight run)
Decision: T2 Q-5 precedent: the owner runs `git init` and the first commit (`T4-00: plan`). Preflight fails without it.
Owner answer (2026-10-12, in chat): approved overnight run; Claude runs git init + the T4-00 commit, and copies OPENAI_API_KEY from T2's .env file-to-file without displaying it.

---

## Overnight decisions
(Workers append here: `## Q-N <title> — H|M|L`, date, goal, decision, why, reverse.)
