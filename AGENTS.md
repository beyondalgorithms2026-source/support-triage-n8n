# AGENTS.md — standing law (T4)

Harness: Thin Ledger v0.1 (`THIN-LEDGER-v0.1.md`). The repo is memory; chat is not. Same law as T2
(`../rescue-diagnostic-t2/AGENTS.md`) with the T4 differences marked **T4**.

## Read before any edit
1. This file
2. `HANDOFF.md` (static start-here), `.ai/HANDOFF.md` (last session's RAM), `.ai/STATUS.md`
3. `docs/DECISIONS.md` + the ADRs and the `docs/ARCHITECTURE.md` / `docs/HARNESS_SPEC.md` sections your goal cites
4. Your goal's section in `GOALS.md` (**T4**: GOALS.md replaces T2's `specs/*/plan.md` + `tasks.md`)
5. `git status`, recent relevant commits
6. Only the source files the goal names

## Authority order
AGENTS.md → accepted ADRs (`docs/adr/`) → `docs/ARCHITECTURE.md`, `docs/HARNESS_SPEC.md`, `docs/SECURITY_CONTROLS.md`
→ `GOALS.md` → existing conventions → model preference

## Rules
- One goal (`Gn` = task `T4-0n`) per session. Task ids are always `T4-NN`, never bare T1–T9.
- Frozen contracts (gold format, manifest, scorecard columns, cost ledger, failure taxonomy, dedupe keys, sandbox
  contract) change only in an architecture session. **T4**: record the need in `OPEN_QUESTIONS.md` instead.
- No drive-by refactors. No new subsystem, database, dependency, framework, dashboard, agent/MCP layer, or public API.
  ADR cap is 7 and all 7 are used.
- Search `src/common/` before writing a helper. Port from T2 by reading its file, not by importing it.
- Python ≥ 3.9 standard library only. `node` only to run `src/js/*.js` in tests. No pip, no npm, no brew.
- All data synthetic, English, US/EU SaaS context (ARCHITECTURE I-1). Never hand-type timestamps, token counts,
  costs, metrics or thresholds; they come from runs (I-6).
- Never write secrets to any file. `.env` is gitignored and is read only by `src/replay/run.py` and `scripts/`.
  Workflow JSON references credentials by name only and uses placeholders, never `$env` (I-10).
- Live model calls only through `python3 -m src.replay.run`, which enforces `RUN_USD_CAP` and `PROJECT_LLM_USD_CAP`.
- Never call a real Jira, Slack or email system. Replay uses the local sink/sandbox (ADR-003).
- Thresholds and prompts are tuned on the `dev` split only (I-9).
- Never use the words secure, certified, compliant, pentested, production-ready about this work.
- Reviewer reports findings (file:line + how it fails); reviewer does not rewrite.
- Stuck on an architecture question → write it in `OPEN_QUESTIONS.md`. **T4 unattended (overnight)**: do not stop;
  choose the most reversible option, record it there with date and cost to reverse, and continue.
- **T4 unattended**: do not commit, push, stash, reset or delete; do not edit `.ai/STATUS.md`, `GOALS.md`,
  `scripts/`, `AGENTS.md`, `CLAUDE.md`, `overnight.conf`. The loop owns commits and status.

## Closeout (every goal)
Before you stop, overwrite `.ai/REVIEW.md`. Do not append.
Write 80% ASD-STE100: one fact per sentence. Max 12 lines. No synonyms. No praise.

Use these headings only:
- Changed: files you edited.
- Did: the one goal you finished.
- Did-not: files and goals you left alone.
- Check: the command you ran, and the result.
- Risk: one thing still open. Write "none" if there is none.
- Next: the next goal id from GOALS.md.

Add one mermaid diagram of the path you touched. If it needs more than 12 nodes, the goal was too big: say so in Risk.
Do not make an HTML page. Do not make a video. Do not add a dependency.
Overwrite `.ai/HANDOFF.md` with the Thin Ledger §5 template (Task, Branch, Last commit, Done, Next task, Read first,
Do not change, Tests run / result, Open questions).
Print the REVIEW card as your final reply. The file and the reply must match.

## Commands (real)
```bash
python3 -m unittest discover -s tests -t . -v          # tests (exist from G1)
python3 -m compileall -q src tests                     # syntax check (no linter / type checker by design)
bash scripts/accept.sh G<n>                            # the goal's acceptance contract
bash scripts/guard.sh                                  # secrets, deps, imports, banned words, protected files
python3 -m src.checks.static_checks --strict --out /dev/null workflows/t4-triage.json   # from G7
```
Do not claim tests passed unless you ran them in this session and saw the output.

## End of session (daytime, human-driven)
1. `git diff` — drop anything unrelated to the goal. Expected 2–12 files; more → stop and explain.
2. Run the commands above.
3. Overwrite `.ai/HANDOFF.md`; update `.ai/STATUS.md` with `python3 scripts/status.py set …`.
4. One focused commit `T4-0n: <goal title>`. New session for the next goal.
