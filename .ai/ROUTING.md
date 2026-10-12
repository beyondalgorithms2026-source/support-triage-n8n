# Routing

Classes are law; the vendor mapping is config (T2 `.ai/ROUTING.md`).

| Class | Use for in T4 | Not for |
|---|---|---|
| Frontier reasoning | Architecture, ADRs, security attack design (G11), findings narrative (G13) | Fixtures, README tables, commits |
| Coding agent | Sink/sandbox (G5), runner (G6), workflow JSON (G7, G8), scorer (G3) | Changing frozen contracts |
| Cheap coding | Generator details (G2), redaction vectors (G4), static checks (G1), runbook (G12) | Security design, taxonomy changes |
| Local small / cheap prose | HANDOFF drafts, commit messages | Decisions, anything with numbers |

## Current mapping (2026-10-12)
- Overnight build: Claude Code CLI, model `opus` with fallback `sonnet` (`overnight.conf`), all goals. This breaks the
  Thin Ledger mix (frontier ≤ 10%) for one night by owner choice; recorded in OPEN_QUESTIONS Q-16.
- Review: a different family (Codex / GPT) reviews G7, G8 (controls) and G13 (findings) before anything is published.
  Until then, findings disclose "same-family author and checks" (T2 precedent).

## Rules
- Author ≠ reviewer family whenever a control is added.
- One dirty tree, one writer. The overnight loop is the only writer while it runs.
- Escalate on evidence: a goal failed twice, crosses a trust boundary, or touches a frozen contract.
