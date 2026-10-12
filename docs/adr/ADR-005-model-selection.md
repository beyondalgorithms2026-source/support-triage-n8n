## ADR-005: Model = gpt-4o-mini-2024-07-18 with logprob confidence; fallback is the human queue
Status: Proposed (architecture session; human acceptance pending)
Date: 2026-10-12
Decision:
- Classifier: `gpt-4o-mini-2024-07-18` via `api.openai.com` chat.completions, strict JSON schema (three enums),
  temperature 0, `max_tokens` 60, `logprobs: true`, `top_logprobs: 5`, no tools.
- Per-class confidence = probability of the chosen enum value's first token, renormalised over the first tokens of
  all enum values. Enum words are chosen so first tokens differ (G7 verifies on real output and records the token map).
- No automatic second model. LLM error after one retry → review. A model change is a manual config change followed by
  a new dev run, new thresholds and a new test run.
- DeepSeek (owner's T2 preference, Q-8) is a documented manual alternative with self-reported confidence.
Reason:
- Same model and prices the owner approved and ran in T2 (2026-10-12): no new vendor, known cost, known behaviour.
- Logprobs give a confidence signal that is far better behaved than a self-reported number, and they are free.
- A silent fallback model would run with thresholds tuned for a different model: wrong routing with no visible error.
Consequences:
- Dependence on OpenAI exposing logprobs together with strict schemas; if G7 shows they are missing, confidence comes
  from self-report and this ADR is revisited (OPEN_QUESTIONS Q-2).
- Provider outage = 100% to human queue until it recovers. That is visible in Slack and the metric.
- Ticket text (redacted) goes to OpenAI; the owner checks current data-retention terms (out of scope here).
