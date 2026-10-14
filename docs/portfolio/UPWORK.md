# Upwork portfolio item — ready to paste

Numbers trace to `evals/eval_report.json` (test split). Data is synthetic. Image: `docs/portfolio/snapshot.png`
(1000 × 750 px PNG, 4:3 — Upwork recommends 1000 × 750, min 400 × 300, JPG/PNG; checked 2026-10-14).

**Title**
AI Support Ticket Triage on n8n: Jira + Slack With Measured Accuracy

**Your role**
Solo builder (Spanfold): design, n8n workflow, evaluation harness, attack testing

**Project description**

Problem: Support leads at small SaaS teams read and sort every new ticket by hand before anyone can act on it.

Approach: An n8n workflow strips personal data, asks gpt-4o-mini for category, priority and urgency with a
confidence score, then files a Jira issue and posts to Slack only when confidence clears a per-class cut-off.
Everything else goes to a human review channel with the reason. Same ticket twice never makes two Jira issues.
Tested on 200 labelled synthetic tickets and 20 named attacks (prompt injection, data leakage, cost spikes,
duplicate writes).

Result (100 held-out synthetic tickets): category macro-F1 0.99; P1 recall 92%; 0 personal-data leaks;
0 duplicate Jira issues on replay; 19 of 20 attacks defended, 1 not run; model cost about $0.11 per 1,000
tickets. 79% currently go to a person — a deliberately cautious start.

Limits: synthetic data and a small sample; priority is weaker (macro-F1 0.72, over-calls P3 as P2); auto-routed
precision 0.85 against a 0.95 target. Cut-offs must be re-tuned on real tickets. Not a client deployment.

**Skills**
n8n · AI Automation · OpenAI API · Jira · Slack API · Python · LLM Evaluation · Prompt Engineering

**Links**
- Code and evidence: https://github.com/beyondalgorithms2026-source/support-triage-n8n
- Walkthrough (Loom): <paste after recording>
