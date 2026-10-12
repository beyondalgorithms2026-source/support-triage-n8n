# Thin Ledger v0.1
## File-first coding harness for multi-model work

**Owner:** Beyond Algorithms  
**Status:** Living document. Version the file in Git when the rules change.  
**Audience:** A human starting a project, or the first frontier model asked to design architecture and the repo layout.  
**Not:** A product to build, an orchestrator, or a replacement for Claude Code / Codex.

If you are a model reading this: you are a disposable worker. The repository is memory. Do not rely on this chat continuing. Do not invent architecture when a file already decided it. Do not implement the whole product in the architecture session.

---

## 0. Is “a good harness always better than the best model” true?

**Mostly, with a limit.**

The same weights can look weak or strong depending on the loop, tools, files, stop rules, and tests around them. YC Paper Club (Sep 2026) used that fact as the teaching point: harness quality moved hard-adaptation scores from roughly 30% to 95% on the same class of model. Anthropic’s own Opus 5.5 guide is mostly harness advice (done-state, CLAUDE.md stop rules, task file, review pass), not “buy a smarter weight file.”

What that does **not** mean:

- A small local model in a beautiful harness will not design a security boundary as well as a frontier model.
- A frontier model in a sloppy chat will still write working demos — and then contradict itself on Tuesday.
- You should not spend a week building Prime Agent before the first feature.

Correct assertion:

> For a given model, harness quality usually moves outcomes more than swapping to the next model.  
> For a given harness, a stronger model still wins on irreversible judgment.  
> The expensive mistake is using the strong model as the entire harness.

Thin Ledger is the minimum harness that captures that split: frontier models decide, cheaper models type, tools verify, humans route, Git remembers.

---

## 1. Contract (read this first)

```
Git + a few repo files  = memory
Models                  = disposable workers
Human                   = router
Tests and evals         = how we know
Chat history            = not memory
```

Preserve decisions, state, interfaces, acceptance criteria, and evidence.  
Do not preserve conversations.

Two loops that must not be fused:

| Loop | Question | Lives in |
|---|---|---|
| **Coding harness (this doc)** | Can the next model continue the *code*? | AGENTS.md, ADRs, HANDOFF, Git |
| **Product evals** | Is the *product output* acceptable? | traces, gold set, rubric — see §8 |

Do not build LiteLLM + n8n + sub-agent councils + a skills zoo before the next feature. That is costume. This file is the costume you skip.

---

## 2. What a harness is (short)

A raw model is tokens in, tokens out.

A harness is everything that lets it finish a job: loop, tools, files, sandbox, permissions, stop rules, tests.

Claude Code, Codex CLI, Cursor, Cline, Aider, Antigravity are already harnesses. Thin Ledger does **not** wrap another runtime around them. It is the **shared filing cabinet** those runtimes read, plus routing rules so you do not spend frontier tokens on lint.

Context as cache:

- **L1** — model weights. Do not fine-tune to remember folder names.
- **L2** — this prompt. Keep it small.
- **L3** — disk: this repo. Large, cheap, searchable.

Bad habit: treat L2 as memory (100-turn chats, paste the repo).  
Good habit: treat L3 as memory; keep L2 to the current task.

---

## 3. Repo layout the first frontier model must create

When starting a **new** project, the architecture session produces files, not application code.

```
repo/
├── AGENTS.md                 # standing law for every agent
├── CLAUDE.md                 # exactly: @AGENTS.md
├── README.md                 # humans; setup and use
├── docs/
│   ├── ARCHITECTURE.md       # what exists now
│   └── DECISIONS.md          # tiny ADRs
├── .ai/
│   ├── HANDOFF.md            # RAM for the next session (overwrite)
│   ├── STATUS.md             # milestone state
│   ├── ROUTING.md            # model classes, not vendor loyalty
│   └── QUESTIONS.md          # stop here instead of inventing
├── specs/
│   └── <feature>/
│       ├── spec.md
│       ├── plan.md
│       └── tasks.md
├── evals/                    # product evals, not coding ceremony
│   ├── README.md
│   ├── gold.jsonl            # when the product has outputs
│   └── rubric.md
└── src/  tests/              # created when implementation starts
```

Rules for those files are in §4–§5. Do not create thirty AI files. Do not create vendor-specific memory files (`CLAUDE_MEMORY.md`, `CODEX_MEMORY.md`).

---

## 4. How a new project starts (human + first frontier model)

### Session A — constitution (human, 30–60 min)

1. `git init`
2. Create the empty skeleton above.
3. Put **real** test / lint / type commands in `AGENTS.md` as soon as the stack is chosen. Placeholders are a smell.
4. Copy routing classes into `.ai/ROUTING.md` (keep vendor names in a private note, not as law).

### Session B — architecture only (frontier reasoning)

Give the model this document + a 10-line intent.  
**Done means:**

- `docs/ARCHITECTURE.md` describes components, boundaries, dependency direction, security boundaries, invariants
- `docs/DECISIONS.md` has ADRs for every expensive-to-reverse choice
- `specs/<feature>/` has spec + plan + checkbox tasks for slice 1 only
- `.ai/HANDOFF.md` names the next implementation task and the files that must not be touched
- `.ai/QUESTIONS.md` lists anything that would require invention
- **no application feature code**

Stop. Human accepts the spec and ADRs. That minute is the highest leverage in the project.

### Session C onward — one checkbox per session

Cheapest capable model class. One commit-sized job. Tests. Update HANDOFF. Commit. New session.

---

## 5. File contracts

### AGENTS.md (standing law)

Must include:

- Required reads before edits: this file, HANDOFF, STATUS, relevant ARCHITECTURE / ADRs, `git status`, only task-relevant source
- One task per session
- Architecture files outrank model preference
- No drive-by refactors; no new subsystem / DB / auth model / public API without an ADR or a question
- Search for an existing abstraction before creating another
- Run the real test/lint/type commands; do not claim tests passed unless run
- Reviewer reports findings; reviewer does not rewrite
- End of session: diff, drop unrelated changes, tests, update HANDOFF (and STATUS if milestone moved), focused commit
- If stuck on architecture: write `.ai/QUESTIONS.md` and stop

Authority order:

```
AGENTS.md
  → accepted ADRs
    → ARCHITECTURE.md
      → task spec
        → existing conventions
          → model preference
```

### CLAUDE.md

```
@AGENTS.md
```

Plus, for Claude Code / Opus 5.5 long runs, these stop rules (from Anthropic’s Opus 5.5 guide; edit to taste):

```
When a step doesn't need my input, keep going.
Put status notes in the same message as your next action.
Stop and ask only when you can't continue without me, or before
anything destructive: deleting data, force-pushing, or changing
anything outside this repository.

End every run with three headings: Blocked on me, Changed, Found.

Keep a checklist in specs/<feature>/tasks.md or TASKS.md.
Tick items when done. Do not rely on chat scrollback.

Do not add “think hard”, “think step by step”, or “always
double-check / verify twice” lines. Effort is set in the tool.
Do not ask to reproduce hidden chain-of-thought in the reply.
```

### HANDOFF.md (RAM — overwrite)

```
# Current handoff
Task:
Branch:
Last commit:
Done:
Next task:
Read first:
Do not change:
Tests run / result:
Open questions:
```

A new model picks up from this plus Git. It does not need yesterday’s chat.

### DECISIONS.md (tiny ADRs)

```
## ADR-00N: <title>
Status: Accepted | Proposed | Superseded
Date: YYYY-MM-DD
Decision:
Reason:
Consequences:
```

Example invariant for RAG-like systems: **ACL is enforced at retrieval, before rerank and before any text enters the generator. Cache keys include principal scope.**

### ROUTING.md (classes, not brands)

See §6. Vendor mapping is a config change, not a process change.

---

## 6. Model routing

### Classes

| Class | Use for | Do not use for |
|---|---|---|
| **Frontier reasoning** | Architecture, security boundaries, irreversible data-model, cross-layer debug, high-risk review | CRUD, lint, unit tests, README, commits, HANDOFF |
| **Coding agent** | Repo-aware implementation, integration, moderate debug, review | Inventing architecture |
| **Cheap coding** | Well-specified functions, unit tests, fixtures, mechanical refactors, small bugs with a failing test | Security design |
| **Cheap prose / long-context** | Docs, release notes, log summaries | Decisions |
| **Local small** (Ollama on 8GB) | Commit messages, HANDOFF drafts, classify the task | Multi-file implementation, architecture |

Illustrative mapping (replace whenever prices or quality move):

- Frontier: Claude Opus-class, GPT/Codex reasoning-class, Gemini reasoning-class
- Coding agent: Claude Code, Codex CLI, capable hosted GLM/DeepSeek/Gemini agents
- Cheap coding: DeepSeek / GLM / smaller hosted coding models
- Local small: Gemma / Ministral / Qwen-class on Ollama — **secretary, not engineer**

Target mix on a normal day: 5–10% frontier, 20–30% coding agent, 40–60% cheap coding, 10–20% prose/local. Zero-frontier days should be normal. If frontier is 70% of coding, routing has failed.

Escalate on **evidence** (failed twice, crosses a boundary, security), not on anxiety.

Author and reviewer = **different model families** when practical. Reviewer lists block-merge issues with file:line. Then a different session fixes them.

### How to switch tools (do not force one IDE)

Match the **native harness** to the model. VS Code is a surface, not the brain.

| Work | Where to run it | Why |
|---|---|---|
| Architecture, hard debug, Claude-family review | **Claude Code** (terminal) or Claude app on Opus | Best loop + CLAUDE.md + subagents + long runs |
| Implementation on Codex/GPT family | **Codex CLI** in the same repo | Native AGENTS.md discovery, git-native |
| Cheap / OpenRouter / DeepSeek / GLM / Kimi | **VS Code + Cline or Continue** (or Aider in terminal) pointed at that API | BYOK, no need to burn Claude quota |
| Local Ollama clerical | Continue / Aider / a one-shot prompt | 8GB cannot be the main coder |
| Parallel terminal agents, Google stack | **Antigravity** if already in use | Optional; not required for Thin Ledger |
| Quick edit while reading files | VS Code as editor only | You can edit in VS Code and run agents in the terminal beside it |

Rules:

- One dirty tree, one writer. If two agents must run, use **git worktrees**, not two chats on the same uncommitted files.
- Do not auto-switch models mid-file.
- Do not sync raw chats between vendors.
- OpenRouter or LiteLLM is optional **later**, as aliases (`frontier_reasoning`, `cheap_coding`). Week one: pick the tool by hand.

On MacBook Air M2 8GB: do not rent a permanent GPU “to save money” until a month of cheap-API spend is measured. Spot GPU only for a defined batch job.

---

## 7. Session protocol (every model, every day)

**Start**

1. Read AGENTS.md, HANDOFF, STATUS, relevant ADRs.
2. `git status`. Inspect recent relevant commits.
3. Open only the files the task names.
4. Restate: outcome, acceptance, files, constraints.
5. If architecture is missing: QUESTIONS.md, stop.

**During**

- One commit-sized task.
- Done-state in the first message (Opus 5.5 and peers work better with a finish line).
- Mid-run addenda are fine; do not restart a long run to add a sentence.
- Keep the checkbox file updated so compaction does not eat the plan.

**End**

1. `git diff` — drop unrelated changes.
2. Run targeted tests / lint / types.
3. Update HANDOFF (and STATUS if needed).
4. Commit.
5. Clean tree. **New session** for the next task.

Diff smell: expected 2–4 files, actual 17 → stop.

---

## 8. Product evals (adjacent — not inside the coding harness)

Evals answer “is this RAG answer / agent action acceptable?”  
They do not belong in AGENTS.md as a skills zoo. They belong in `evals/` once the product emits traces.

### Philosophy (Hamel / Shreya)

- Look at data first. Externalize taste **before** writing judges.
- **Top-down** evals: what a domain expert would require in a vacuum (ACL, citations, refuse when empty). Models help draft these.
- **Bottom-up** evals: what you notice when you sit with real outputs. Models are bad at inventing these. That is the human.
- Prefer **yes/no** checks, not “quality = 7.”
- One LLM judge per named failure mode. Fan out if the rubric is long.
- Auto-eval buttons catch obvious breakage. They miss product judgment. You still read traces.
- Do not ask a model to “add evals” after one bad demo — that overfits.

### For a RAG-like product

Top-down (accept, then freeze):

- Unauthorized chunks never enter the generator or citations
- Every factual sentence maps to a surviving chunk ID
- Weak retrieval → explicit don’t-know / refuse
- Cache key includes ACL scope

Bottom-up (you write after 15–30 traces):

- Table numbers lost in parse
- Hedging words not in the source
- Wrong doc type retrieved
- Warm cache mixed tenants

Then: gold.jsonl of {query, principal, must_retrieve, must_not, accept_or_refuse}.  
Run it when you change chunking, reranker, or generator model. That is how cheap-model routing stays safe.

Error analysis is a **product workspace**, not a coding-handoff file. Optional: a small review UI over traces. Required: the gold set and the rubric.

---

## 9. Frontier-model operating notes (Opus 5.5 and peers)

These are tool-specific. They do not replace Thin Ledger; they sit inside Claude Code when that is the worker.

From Anthropic’s “Getting the most out of Opus 5.5” (Sep 2026):

1. Hand over the **whole task** and say what done looks like. Then let it run.
2. Delete “think carefully / think hard / think step by step” from prompts and saved instructions. The model already allocates thought. For a quick answer, say “answer directly.” Control depth with **effort**, not adjectives.
3. Name **when to stop vs keep going** in CLAUDE.md (already in §5).
4. Long audits: split across **subagents**, then check each one’s evidence. Parent writes one table.
5. Keep the task list in a **file** (tasks.md). Scrollback dies when the window is compacted.
6. When a run ends, read **Blocked on me** first.
7. Review pass: only merge-blockers, file + line + how to show it fails. Prefer a **different family** for review when cost allows.
8. Research: mark what could not be confirmed.
9. Attach screenshots/diagrams; do not retype them.
10. Fast mode (`/fast`) for interactive back-and-forth. Standard mode for unattended long jobs.
11. If a safety flag switches you to an older model: `/model` back, or new chat. Do not ask it to dump hidden reasoning.
12. Keep permission prompts **on** for destructive commands.

Thin Ledger adds: architecture session still does not write the feature. A long autonomous run is for an **accepted checkbox**, not for inventing ADR-007.

---

## 10. What not to build in week one

- Multi-agent councils (architect, critic, QA, consensus)
- Mid-file automatic model switching
- Chat-history vector databases so Codex can “remember Claude”
- LangGraph / n8n driving the coding loop
- Vendor-specific memory files
- A self-improving Darwin harness
- Renting an always-on GPU to avoid DeepSeek API invoices without measuring spend

Automate only after the same mechanical workflow has repeated often enough that inputs, routing rule, outputs, and failures are stable.

---

## 11. Prompt to paste into the first frontier model

```
You are the architecture worker for this repo. Read THIN-LEDGER-v0.1.md
and obey it.

My intent (edit this block):
- Product:
- Users:
- Non-goals:
- Constraints (stack, privacy, time):
- Slice 1 (the only thing we will implement next):

Done means you have written or updated:
- AGENTS.md (with placeholder commands marked TODO only if the stack
  is not yet chosen; prefer real commands)
- CLAUDE.md importing AGENTS.md plus stop rules
- docs/ARCHITECTURE.md
- docs/DECISIONS.md (one ADR per irreversible choice)
- specs/<slice>/spec.md, plan.md, tasks.md
- .ai/HANDOFF.md, STATUS.md, ROUTING.md, QUESTIONS.md
- evals/README.md describing how we will judge product outputs
  (no fake gold set)

Do not write application feature code.
Do not invent decisions: put options in QUESTIONS.md.
Do not add dependencies or frameworks not implied by the intent.
End with: Blocked on me, Changed, Found.
```

---

## 12. Versioning this harness

- File: `THIN-LEDGER-v0.1.md` at repo root or in a personal `harness/` folder copied into each new project.
- Bump the version when a rule changes (stop rules, routing table, eval policy).
- Do not grow this into a book. If a section is unused for two projects, cut it.

**Changelog**

- v0.1 (2026-09-25) — First consolidation from the multi-model / YC harness / Opus 5.5 / Hamel-Shreya evals thread. Static file-first harness. Evals adjacent. No orchestrator.
---
