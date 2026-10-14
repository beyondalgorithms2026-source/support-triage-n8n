# T4 close plan — 2026-10-14

Living checklist. Tick `[x]` when done; record decisions under each section and in the Decision log at the end.
Owner key: **Me** = Spanfold owner (human). **AI** = Claude session. Minutes are estimates.
Budget: **$4.00 API max today**; estimate shown before any paid run; no overnight runs.

## 0. State re-verified (14 Oct, this session) — differs from the 13 Oct audit

| Audit said | Verified now | Effect on plan |
|---|---|---|
| G11 uncommitted | G11, G12, G13 **committed** (`e6ece8e`, `5dafe3a`, `ec5f703`); tree clean | Step 1.1 becomes "review the committed G11 diff", not "commit" |
| G12–G14 not started | G12 + G13 DONE in `.ai/STATUS.md`; **only G14 (buyer README) TODO** | Section 5 shrinks to G14 + review of G12/G13 |
| 232 tests | **242 tests, OK** | — |
| 75% to human | `eval_report.json`: 75 human of **95 considered** → `pct_human` **0.789**; 75/100 if counted on all tickets | Publish **79%** (the report's own number). "75%" is not traceable — drop it |
| Category 92/100, priority 67/100 | Category macro-F1 0.989 on 93 classified; priority macro-F1 0.719; P3 recall 14/36 | Use report numbers only (I-6); recompute "x/100" phrasing from report or drop it |
| — | `metric_status`: auto_route_precision **0.85 = breach** (target 0.95); pct_human **breach** (target ≤0.40) | Must be stated plainly in README and Upwork copy |
| — | SEC: 19 defended, 0 failed, 1 not_run (SEC-17) | Findings table already generated |
| — | **No LICENSE file**; "Beyond Algorithms" only in `THIN-LEDGER-v0.1.md:4` (+ git author) | Brand step creates LICENSE |
| — | OWASP: repo uses **LLM Top 10 2025** + Agentic ASI (Dec 2025) per Q-9. I know of no "2026" LLM Top 10 | Decision D-3 below |
| — | No gitleaks/trufflehog installed; `brew`/`pip` banned in-repo | Decision D-2 below |
| Spend $46.13 | `evals/cost_ledger.csv` holds model spend only; loop spend lives in `logs/` | Re-read, don't re-type |

---

## 1. Safety first

- [ ] **1.1 Review G11 work** — AI, 15 min. `git show e6ece8e --stat` + G11 commit; run `bash scripts/accept.sh G11`, `G12`, `G13`, `bash scripts/guard.sh`. Report findings file:line. *Done means:* all four pass, output pasted here.
- [ ] **1.2 Secret scan, full history** — AI, 15 min. Without new deps (D-2): (a) `git log -p --all` piped through a scratchpad Python scanner using the same patterns as `scripts/guard.sh` / SEC-20 plus generic (`sk-`, `xox[bpa]-`, `ATATT`, `-----BEGIN`, `AKIA`, `ghp_`, high-entropy 32+ chars), and (b) check every `.env` key *name* from `.env` against history (values compared in-process, never printed). (c) `git log --all -- .env` must be empty. *Done means:* 0 hits, or each hit triaged as fake/fixture with file:commit.
- [ ] **1.2b Optional stronger scan** — Me, 5 min: `brew install gitleaks && gitleaks git .` outside the repo rules. *Done means:* "no leaks found".
- [ ] **1.3 Create remote** — Me (creates repo, 3 min), AI (pushes after "GO" + clean scan, 2 min).
  **Recommendation: public** GitHub repo `spanfold/support-triage-n8n`. Why: an Upwork/LinkedIn reviewer will not request access to a private repo; a public repo lets a buyer click from claim to evidence (`eval_report.json`, `SHA256SUMS`) in one minute, which is the whole selling point. Risk is low: data is synthetic, no client code. **Gate:** public only if 1.2 is clean; otherwise private until history is rewritten (rewrite = destructive → asks you).
  *Done means:* `git remote -v` shows origin; `main` pushed; repo page loads logged out.

## 2. Questions T4 must answer (plain English, all from existing outputs — $0)

AI writes these into `evals/findings.md` (owner section) / README / LIMITATIONS only where numbers already exist in `eval_report.json`; new numbers come from a script (2.3) whose output is committed.

- [ ] **2.1 Problem and buyer** — Head of Support at a 20–200 person SaaS. Every new ticket is read, labelled (category, priority, urgency), and either filed in Jira + announced in Slack, or held for a person. Saves first-touch triage time; never silently guesses.
- [ ] **2.2 Why ~79% goes to a human** — three causes, all visible in `scorecard.csv` notes `outcome=review/auto_route`:
  1. Policy, not confidence: `privacy`, `other` always review (ADR-002); `outage`, `feature` τ=1.01 (dev split too small to prove ≥0.95 precision, so tuner refused them).
  2. Priority gate: τ_P2 = 1.01 → **every predicted P2 goes to review**. The model predicts P2 for 21 of 36 true-P3 tickets, so most of the review volume is P2 over-calls.
  3. Safety: injection flag, malformed, high urgency. These are intended.
- [x] **2.3 Threshold sweep, no API calls** — AI, 30 min. Script in scratchpad replays `decide` over the committed test `scorecard.csv` confidences under scenarios: (A) committed per-class τ; (B) global τ=0.5 (already in report: 49% coverage, 0.878 precision); (C) τ_P2 lowered to 0.95/0.90; (D) C + `feature`/`outage` category τ=0.95; (E) D + P2 merged with P3 for routing only. Table columns: scenario, % human, auto-routed, auto precision, misroute_auto, priority_miss_auto, unsafe_auto. **Caveat in the table:** tuned on test = optimistic; any adopted change must be re-tuned on `dev` (I-9) and re-validated on test (paid run, 2.3b).
  **Result (run 2026-10-14, $0, script re-scores committed run folders with `src.score.report`-style `eligible()` logic):**

**dev** (`dev-local-20261013T034424Z-3accb59`)

| Scenario | Considered | Auto-routed | % to human | Auto precision (cat+prio both right) | Wrong category | Wrong priority | P1 under-called |
|---|---|---|---|---|---|---|---|
| A committed per-class τ (published) | 91 | 17 | 81% | 0.94 | 0 | 1 | 0 |
| B P2 τ 1.01→0.95 | 91 | 34 | 63% | 0.74 | 0 | 9 | 1 |
| C B + outage/feature τ 0.95 | 91 | 54 | 41% | 0.80 | 2 | 9 | 1 |
| D global category τ 0.5, committed priority τ | 91 | 35 | 62% | 0.94 | 1 | 1 | 0 |
| E D + P2 τ 0.95 | 91 | 55 | 40% | 0.78 | 3 | 9 | 1 |
| F E + P3 τ 0.5 | 91 | 58 | 36% | 0.76 | 3 | 11 | 1 |

**test** (`test-local-20261013T040225Z-0814c13`)

| Scenario | Considered | Auto-routed | % to human | Auto precision (cat+prio both right) | Wrong category | Wrong priority | P1 under-called |
|---|---|---|---|---|---|---|---|
| A committed per-class τ (published) | 93 | 20 | 78% | 0.85 | 1 | 2 | 0 |
| B P2 τ 1.01→0.95 | 93 | 39 | 58% | 0.69 | 1 | 11 | 1 |
| C B + outage/feature τ 0.95 | 93 | 60 | 35% | 0.77 | 1 | 13 | 1 |
| D global category τ 0.5, committed priority τ | 93 | 41 | 56% | 0.88 | 1 | 4 | 0 |
| E D + P2 τ 0.95 | 93 | 60 | 35% | 0.77 | 1 | 13 | 1 |
| F E + P3 τ 0.5 | 93 | 60 | 35% | 0.77 | 1 | 13 | 1 |

  Denominator here = tickets that reached the classifier (93 test). `eval_report.json` counts 95 "considered" (2 more that never reached the model), so A shows 78% here and **79%** in the report; publish the report number.

  **Reading the curve:** lowering τ_P2 (B, C, E, F) buys coverage with priority errors (precision 0.94 → 0.74 on dev) and lets one P1 slip through as P2. A single global category τ (D) keeps dev precision at 0.94 while cutting the human share 81% → 62% on dev and 78% → 56% on test (test precision 0.85 → 0.88). Category is not the problem; priority is.
- [ ] **2.3b (optional, paid)** — re-run test split with new thresholds. Estimate from ledger: test run = $0.0105; dev = $0.0101; attack = $0.0228 → **≈$0.05 total, plus Claude session cost.** Shown to you before running.
- [ ] **2.4 Recommend final cut-offs** — AI proposes, **Me decides**. Expected recommendation: keep committed τ as the published v1 ("conservative start") — yes, 79% to human is defensible **only** when framed as: day-1 shadow mode, 0 unsafe auto-routes, 0 PII leaks, and a written path to ~40–50% once 2–4 weeks of real reviewed tickets re-tune P2 and outage/feature. Not defensible as an end state.
- [ ] **2.5 Priority honest fix** — macro-F1 0.719. The model over-escalates P3→P2 (21/36). Honest fix, in order: (1) priority rubric in the prompt with 2 examples per level (dev split only); (2) derive priority from category+urgency rules and let the model only flag exceptions; (3) more P2/P3 boundary gold labels — also a gold-label question for you (§3). Not done today unless you choose 2.3b; listed in LIMITATIONS.
- [ ] **2.6 Failure taxonomy with counts** (test run, from report): schema_miss 0 · misroute_auto **1** (t4-110 feature→howto) · priority_miss_auto **2** (t4-147, t4-192) · unsafe_auto 0 · duplicate_issue 0 · silent_drop 0 · pii_leak 0 · injection_followed 0 · unbounded_spend 0 · retry_storm 0 · audit_gap 0 · notify_gap 0. Plus 1 `error` outcome (t4-075) → investigate in 1.1.
- [ ] **2.7 G11 findings mapped to OWASP** — table exists: `evals/security_findings.md` (20 rows, 19 defended, SEC-17 not_run). Mapping uses LLM Top 10 **2025** + Agentic Top 10 (ASI). See D-3 for "2026". AI verifies IDs against owasp.org pages (web, $0) — 10 min.
- [ ] **2.8 Cost** — test run: **$0.000105/ticket mean, $0.105 per 1,000 tickets** (gpt-4o-mini, model cost only; excludes n8n hosting and build cost). Attack run $0.000219/ticket (larger inputs). Build cost (Claude overnight) reported separately from `logs/`, labelled as one-off.
- [ ] **2.9 Limitations** — `docs/LIMITATIONS.md` exists; AI adds: auto-route precision breach (0.85 vs 0.95), 79% human, priority over-escalation, n=93 small sample, synthetic data, sandbox-only integration until §4 done, SEC-17 not run, OWASP numbering caveat.

## 3. Your review gates (≤20 min total) — Me

**Gold labels (12 min).** AI first prints a 30-row sheet `docs/plans/gold_review_30.md` (id, subject, first 200 chars, category/priority/urgency/outcome gold, model output, mismatch flag). Selection: all 13 test tickets where gold ≠ model (P3↔P2 ones first), t4-110/147/192/075, plus random fill to 30. For each row tick one:
- [ ] Category is what a support lead would pick (yes / change to …)
- [ ] Priority: would you page someone? P1=down/data loss, P2=major broken for many, P3=one user blocked, P4=question/request. **Key call:** are the P3-labelled tickets the model calls P2 really P3? If ≥5 should be P2, the gold is wrong, not the model → affects 2.5.
- [ ] Outcome: privacy/other → review is acceptable to you
- [ ] No real person, company, email, or non-synthetic content
Changed labels → recorded here; relabel is a gold change → requires re-score (no API cost: score-only) and regenerating the report.

**ADRs (8 min, ~1 min each).** One question each; tick accept or write "reject: why".
- [ ] ADR-001 per-class thresholds — OK that untunable classes go to review (τ=1.01)?
- [ ] ADR-002 human queue is a designed outcome — OK that privacy/other always go to a person?
- [ ] ADR-003 Jira sandbox — OK that the sandbox stays the default and real Jira is opt-in demo only?
- [ ] ADR-004 redaction before model — OK that redaction is pattern-based (names/addresses can pass)?
- [ ] ADR-005 model gpt-4o-mini — OK with a 2024 model for the published numbers (logprob Q-2)?
- [ ] ADR-006 idempotent Jira writes — OK with label-search dedupe and the SEC-17 lag gap?
- [ ] ADR-007 spend cap by day — cap values acceptable?
*Done means:* every box ticked; changes in Decision log; `evidence_status` may move `candidate` → `accepted` in the report (AI regenerates).

## 4. Real Jira + Slack demo (free tiers) — sandbox stays default

Architecture note: ADR-003 + AGENTS forbid agents calling real Jira/Slack. Real mode is an **owner-run demo** path only. Adding it = small change to sink/workflow credentials (no new dependency; urllib). This touches a frozen contract boundary → **D-1, needs your OK**.

**Your setup (Me, ~35 min):**
- [ ] Jira Cloud Free: atlassian.com → Jira free → site `spanfold-demo.atlassian.net` → project **Scrum/Kanban, key `TRI`**. Add labels allowed (default). 8 min.
- [ ] Jira bot user: use a separate Atlassian account if possible (least privilege: member of TRI only, "Browse projects" + "Create issues" + "Edit issues"; no admin). API token at id.atlassian.com → Security → API tokens, expiry 7 days. 7 min.
- [ ] Slack free workspace `spanfold-demo`, channels `#triage-alerts`, `#triage-review`. 5 min.
- [ ] Slack app (api.slack.com/apps → From scratch) → **Incoming Webhooks** on → one webhook per channel. No bot token, no OAuth scopes beyond `incoming-webhook`. 8 min.
- [ ] Put values in `.env` (gitignored) yourself. **Names only:**
  `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`, `SLACK_WEBHOOK_ALERTS`, `SLACK_WEBHOOK_REVIEW`, `T4_SINK_MODE` (`sandbox` | `real`, default `sandbox`).
  In n8n: create credentials named `t4-jira-demo` (Basic Auth) and `t4-slack-alerts`/`t4-slack-review` (header/URL). Workflow JSON references names only (I-10).

**AI build (~45 min, after D-1):**
- [ ] Real-mode adapter behind `T4_SINK_MODE=real`; same dedupe key as label `t4-<dedupe_key>`; JQL search before create (C-18).
- [ ] `scripts/demo_real.sh` (**owner runs it**; agent never does): sends 1 high-confidence ticket → expects 1 TRI issue + 1 `#triage-alerts` message; sends it again → expects 0 new issues, 0 new messages; JQL count by label = 1; exits non-zero otherwise. Prints issue key, never tokens.
- [ ] Unit tests with a fake HTTP server (no network). Sandbox tests unchanged.
- [ ] Cost: 2 LLM calls ≈ $0.0003.
*Done means:* your terminal output shows `issues_created=1 slack_posts=1 replay_new_issues=0`; screenshot saved to `docs/demo/`; token revoked after recording.

## 5. G12–G14

- [ ] G12 runbook/limitations — DONE (committed). AI adds §2.9 lines. 10 min.
- [ ] G13 findings + eval report — DONE. AI fills nothing in "Trace notes (owner)"; **Me** writes 3 lines there (5 min) or leaves placeholder.
- [ ] **G14 buyer README** — AI, 30 min. ≤200 words, no "plan only", every number from `eval_report.json`, links resolve, Spanfold brand, "synthetic data" in first 3 lines, breaches stated. `bash scripts/accept.sh G14` + guard.
- [ ] `python3 scripts/status.py set T4-14 DONE …`; update milestone rows M1–M4 in `.ai/STATUS.md`; overwrite `.ai/HANDOFF.md` and `.ai/REVIEW.md` per AGENTS closeout. 10 min.
- [ ] Commits: `T4-14: Buyer README`, separate `T4-close: …` commits for plan/brand/demo. One goal per commit.

## 6. Loom script (3–5 min) — AI writes `docs/demo/LOOM_SCRIPT.md`, Me records (30 min incl. retakes)

| # | Segment (time) | Screen | Setup command | Spoken line (draft) | Fallback |
|---|---|---|---|---|---|
| 1 | Hook (0:00–0:20) | README top | — | "Support leads triage every ticket by hand. This reads each one, labels it, and only acts when it is confident. All data here is synthetic." | — |
| 2 | Ticket in (0:20–0:45) | Terminal + n8n canvas | `docker start n8n`; `python3 -m src.sink.server` | "A customer ticket arrives at the webhook — with an email and a phone number in it." | Show `evals/inputs` JSON |
| 3 | PII redacted (0:45–1:10) | n8n execution → Redact node output | `python3 -m src.replay.run --one t4-170` (est. $0.0002) | "Before the model sees it, personal data is replaced with tokens. Zero leaks across 100 test tickets." | `scorecard.csv` pii_leak column |
| 4 | Classified + confidence (1:10–1:35) | Classify node output | same | "Category, priority, urgency, each with a confidence score." | scorecard row |
| 5 | Auto-route (1:35–2:05) | Jira TRI board + Slack #triage-alerts | `bash scripts/demo_real.sh` | "High confidence: one Jira issue, one Slack alert." | Sandbox log `jira_issues.jsonl` |
| 6 | Human review (2:05–2:30) | #triage-review + review_queue.csv | ticket t4-034 | "Low confidence goes to a person, with the reason." | csv only |
| 7 | Malicious blocked (2:30–2:55) | Injection ticket t4-161 + flag | `--one t4-161` | "This one tries to order the model around. It is flagged and sent to review; nothing is filed." | security_findings.md SEC-01 |
| 8 | Replay, no dupes (2:55–3:20) | Terminal second run + JQL count | re-run demo script | "Same ticket again: zero new issues." | Pass-B numbers in report |
| 9 | Scorecard (3:20–4:05) | `evals/findings.md` / sweep table | — | "Category accuracy high; priority weaker — it over-escalates. 79% goes to a person today, by design for week one; here is the trade-off curve. About ten cents per thousand tickets in model cost." | — |
| 10 | Limits (4:05–4:40) | LIMITATIONS.md | — | "Synthetic data, small sample, pattern-based redaction, one attack not run. Next step: tune on your real tickets." | — |

## 7. Upwork portfolio item — AI drafts `docs/portfolio/UPWORK.md`, Me pastes (10 min)

- Title (≤70 chars): "AI Support Ticket Triage on n8n — Jira + Slack, With Measured Accuracy"
- Role: "Solo builder: design, evaluation harness, n8n workflow, security testing"
- Description: problem → approach → result (numbers from report, incl. 79% human / 0.85 auto precision) → limits (synthetic, not a client deployment).
- Skills tags (Upwork allows a limited set; verify count): n8n, AI Automation, OpenAI API, Jira, Slack API, Python, LLM Evaluation, Prompt Engineering.
- Links: GitHub repo, Loom.
- [ ] **Snapshot image** — AI renders 1 page (HTML → PNG via headless browser pane screenshot; no new dep). **AI checks Upwork's current image rules on upwork.com help pages before sizing** (my memory: thumbnail ~1000×750, 4:3, ≤10 MB JPG/PNG — to be verified, not assumed). 25 min.

## 8. Public profiles — drafts only (AI, 20 min)

- [ ] `docs/portfolio/LINKEDIN_FEATURED.md`: title + 2-line description + link.
- [ ] `docs/portfolio/spanfold_work_card.html` + copy: self-contained card snippet (title, 1-line result, 3 metric chips, "synthetic data" tag, repo + Loom links). **Site not touched.**

## 9. Brand (AI, 10 min)

- [ ] `THIN-LEDGER-v0.1.md:4` owner line → Spanfold. (Allowed in a daytime session; not an overnight-protected file.)
- [ ] README → Spanfold (in G14).
- [ ] **LICENSE does not exist** — D-4: create MIT `Copyright (c) 2026 Spanfold`?
- [ ] Git author name stays "Beyond Algorithms" in history (rewrite = destructive, not proposed). Future commits: optionally `git config user.name Spanfold` — Me decides.

## Budget estimate (shown before any paid run)

| Item | Est. |
|---|---|
| §2.3 sweep, §2.6–2.9, §5–9 | $0 API |
| §2.3b optional dev+test re-run | ≈ $0.03 |
| §4 demo (2 tickets ×2 passes, dedupe skips 2nd LLM call) | ≈ $0.001 |
| §6 Loom live segments (~5 tickets) | ≈ $0.001 |
| **Total OpenAI** | **< $0.05** of $4.00 |

## Decisions needed from you at "GO"

- **D-1** Add owner-run real Jira/Slack mode (touches ADR-003 boundary; sandbox stays default). Reverse: delete adapter + script. *Recommend yes.*
- **D-2** Secret scan with a stdlib scanner (no new deps) + optional gitleaks run by you. *Recommend yes.*
- **D-3** "OWASP LLM Top 10 2026": I am not aware of a 2026 edition; repo uses 2025 LLM list + Agentic ASI. I will check owasp.org; if no 2026 list exists, label as "OWASP Top 10 for LLM Applications 2025 + Agentic Top 10". *Recommend: label truthfully, never "2026" unless it exists.*
- **D-4** LICENSE = MIT, Spanfold. *Recommend yes.*
- **D-5** Publish 79% (report) instead of 75%. *Recommend yes.*
- **D-6** Repo public (if scan clean). Name?

## Decision log
- 2026-10-14 — plan written; state re-verified (§0). Waiting for GO.

---

**T4 is closed when…**
1. Every published number traces to `evals/eval_report.json`, the history secret scan is clean, and the repo is pushed to a (public) remote with G14 DONE in `.ai/STATUS.md`.
2. You have ticked the 30 gold labels and 7 ADRs, and one real Jira issue + one Slack message were created with a replay proving zero duplicates (sandbox still the default).
3. The Loom, Upwork item, snapshot image, LinkedIn text and Spanfold card draft exist, all labelled synthetic, with the limits stated.
