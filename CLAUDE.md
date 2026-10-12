@AGENTS.md

When a step doesn't need my input, keep going.
Put status notes in the same message as your next action.
Stop and ask only when you can't continue without me, or before
anything destructive: deleting data, force-pushing, or changing
anything outside this repository.
When running unattended (the overnight loop, `claude -p`), never stop to ask:
record the decision in OPEN_QUESTIONS.md and continue with the most
reversible option.

End every run with three headings: Blocked on me, Changed, Found.

Keep the checklist in GOALS.md and the task table in .ai/STATUS.md.
Do not rely on chat scrollback.
