# REVIEW — T4-12 (G12) Runbook and limitations note

- Changed: `docs/RUNBOOK.md` (new), `docs/LIMITATIONS.md` (new), `OPEN_QUESTIONS.md` (Q-36), `.ai/HANDOFF.md`, `.ai/REVIEW.md`.
- Did: G12. The runbook has all ten headings and 580 words. The limitations note has 25 bullets, each with an evidence path.
- Did-not: no source, workflow, test, run folder or script changed. No live model call. G13 and G14 not started.
- Check: `bash scripts/accept.sh G12` → ACCEPT PASS. `bash scripts/guard.sh` → guard clean.
- Risk: the pruning settings and the hand-made `t4dk-` issue step are not tested by any run (Q-36).
- Next: G13 (T4-13).

```mermaid
flowchart LR
  A["ARCHITECTURE §11"] --> L["docs/LIMITATIONS.md"]
  R["evals/runs G7–G11"] --> L
  Q["OPEN_QUESTIONS Q-19…Q-35"] --> L
  C["src/replay/run.py CLI"] --> B["docs/RUNBOOK.md"]
  T["src/score tune / check_run"] --> B
  B --> X["accept.sh G12"]
  L --> X
  X --> G["guard.sh"]
```
