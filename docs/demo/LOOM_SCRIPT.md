# Loom script — Support ticket triage (Spanfold), 3–5 min

All tickets are synthetic. Numbers are from `evals/eval_report.json` (test split, 100 tickets). Use only the words
in the Say column for claims (the banned-word list is in AGENTS.md). Say "synthetic" at least once on camera.

## Before recording (10 min)

```bash
docker start n8n
python3 scripts/demo_real.py check
python3 -m src.replay.run setup
```

Open tabs: README on GitHub · n8n canvas (`t4-triage`) · Jira board (demo project) · Slack #triage-alerts and
#triage-review · `evals/findings.md` · `docs/LIMITATIONS.md` · a terminal at repo root, font 18 pt.
Demo tickets (dev split): `t4-173` billing with a synthetic IBAN, email, name → auto-route · `t4-153` injection →
review · `t4-007` privacy → review by policy. Cost of one live run: under $0.001.

## Segments

| # | Time | Screen | Do | Say | Fallback if it breaks |
|---|---|---|---|---|---|
| 1 | 0:00–0:20 | README on GitHub | Scroll to Results | "Support leads read and sort every ticket by hand. This reads each one, labels it, and only acts when it is confident. Everything here runs on synthetic tickets." | — |
| 2 | 0:20–0:45 | Terminal, then `evals/gold/t4-173.json` | Show the ticket body | "Here is a billing ticket. It contains a bank number, an email and a name — all made up." | Same file, no live run |
| 3 | 0:45–1:10 | Terminal | `python3 -m src.replay.run run --phase smoke --ids t4-173 t4-153 t4-007 --real` | "I send three tickets to the n8n workflow. The first step replaces personal data with tokens before the model sees anything." | Show `evals/runs/test-*/` trace for t4-176 (PII, auto-routed) |
| 4 | 1:10–1:35 | n8n execution, node `H6`/`H8` output | Open the t4-173 execution | "The model returns three labels — category, priority, urgency — each with a confidence score taken from token probabilities." | `evals/scorecard.csv` row for t4-178 |
| 5 | 1:35–2:05 | Jira board, then #triage-alerts | Open the new issue | "Confident enough: one Jira issue, one Slack alert. The issue text is the redacted ticket, never model-written text." | Sandbox: `evals/runs/test-*/sink/jira_issues.jsonl` |
| 6 | 2:05–2:30 | #triage-review | Point at the t4-007 post | "This one is about personal data, so by policy a person always decides. The review post says why." | `review_queue.csv` in the run folder |
| 7 | 2:30–2:55 | #triage-review, then `gold/t4-153.json` injection text | Show the hidden instruction | "This ticket tries to order the model to call it a P1 outage. The scan flags it, it goes to review, and nothing is filed." | `evals/security_findings.md` row SEC-01 |
| 8 | 2:55–3:20 | Terminal | Re-run step 3, then `python3 scripts/demo_real.py count` | "Same tickets again, as if the email system retried. Still one issue — zero duplicates." | Report: `max_issues_per_dedupe_key` = 1, pass B creates 0 |
| 9 | 3:20–4:05 | `evals/findings.md`, sweep table in the close plan | Scroll | "On 100 held-out tickets: category is right almost every time; priority is weaker — it over-calls P3 as P2. Today 79% go to a person. That is deliberately cautious for week one. Here is the trade-off: one global cut-off would take that to about 56%. Model cost is about eleven cents per thousand tickets. 19 of 20 attacks were defended; one was not run." | — |
| 10 | 4:05–4:40 | `docs/LIMITATIONS.md` | Scroll | "Limits: synthetic data and a small sample, pattern-based redaction, and the cut-offs need re-tuning on your real tickets. The next step with a client is two weeks in shadow mode." | — |

## After recording

```bash
python3 -m src.replay.run setup
```

Revoke the Jira API token. Save screenshots to `docs/demo/`. Paste the Loom URL into `docs/portfolio/UPWORK.md`.
