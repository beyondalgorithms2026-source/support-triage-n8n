## ADR-001: Per-class confidence thresholds, not one global threshold
Status: Proposed (architecture session; human acceptance pending)
Date: 2026-10-12
Decision:
- Auto-routing needs `conf_category ≥ τ_cat[category]` and `conf_priority ≥ τ_pri[priority]`, with one τ per class
  (8 categories, 4 priority levels), tuned on the dev split only (`docs/HARNESS_SPEC.md` §3).
- A class that cannot reach its precision target with at least 5 dev tickets gets τ = 1.01 (always human).
- A global τ is still computed on the same dev run and reported next to the per-class result as the baseline.
Reason:
- Classes differ in how often they are confused and in what a mistake costs. `howto` vs `feature` mixes are cheap;
  `outage` as `bug` delays an incident. One global τ is either too strict for easy classes (sends work to humans that
  the model gets right) or too loose for hard ones.
- The buyer's question is "how much can I safely automate, per queue". Per-class cut-offs answer it directly.
Consequences:
- 12 numbers to maintain instead of 1. They live in `evals/thresholds.json` and the `0. Config` node; a test keeps
  them equal.
- About 12 dev tickets per class: thresholds are noisy. Findings report Wilson bounds and state the limitation.
- Any model, prompt or schema change invalidates the thresholds (ADR-005): new dev run, new tuning, new test run.
