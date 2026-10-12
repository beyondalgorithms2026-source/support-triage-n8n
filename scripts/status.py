"""Read GOALS.md and read/write the task table in .ai/STATUS.md. Only the overnight loop (or the owner) runs `set`.

Commands:
  check                      parse GOALS.md and STATUS.md, print the goal list
  init                       add missing rows to the STATUS table (never changes existing rows)
  next                       print the next eligible goal id (deps DONE, state TODO/IN_PROGRESS) or nothing;
                             marks TODO goals whose deps are BLOCKED/SKIPPED as SKIPPED
  get  Gn FIELD              print task|title|state|attempts|evidence|deps|hours
  set  Gn STATE [--attempts N] [--evidence TEXT]
  json                       print all rows as JSON (morning report)
States: TODO, IN_PROGRESS, DONE, BLOCKED, SKIPPED.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOALS = ROOT / "GOALS.md"
STATUS = ROOT / ".ai" / "STATUS.md"
START, END = "<!-- status-table:start -->", "<!-- status-table:end -->"
HEADER = "| Task | Goal | Title | State | Attempts | Evidence |\n|---|---|---|---|---|---|"
STATES = ("TODO", "IN_PROGRESS", "DONE", "BLOCKED", "SKIPPED")


def parse_goals():
    text = GOALS.read_text(encoding="utf-8")
    goals = []
    for m in re.finditer(r"^## (G\d+) — (.+?)\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S):
        gid, title, body = m.group(1), m.group(2).strip(), m.group(3)
        task = re.search(r"^Task:\s*(T4-\d+)", body, flags=re.M)
        deps = re.search(r"^Depends-on:\s*(.+)$", body, flags=re.M)
        hours = re.search(r"^Hours:\s*([\d.]+)", body, flags=re.M)
        if not (task and deps and hours):
            raise SystemExit("GOALS.md: {} lacks Task/Depends-on/Hours".format(gid))
        dep_list = [] if deps.group(1).strip().lower() == "none" else re.findall(r"G\d+", deps.group(1))
        goals.append({"id": gid, "task": task.group(1), "title": title, "deps": dep_list, "hours": float(hours.group(1))})
    if not goals:
        raise SystemExit("GOALS.md: no goals found")
    return goals


def read_rows():
    text = STATUS.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(".ai/STATUS.md: status-table markers missing")
    table = text.split(START, 1)[1].split(END, 1)[0]
    rows = {}
    for line in table.strip().splitlines()[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6:
            rows[cells[1]] = {"task": cells[0], "goal": cells[1], "title": cells[2], "state": cells[3],
                              "attempts": int(cells[4] or 0), "evidence": "|".join(cells[5:]).strip()}
    return rows


def write_rows(rows, goals):
    text = STATUS.read_text(encoding="utf-8")
    lines = [HEADER]
    for g in goals:
        r = rows[g["id"]]
        ev = r["evidence"].replace("|", "/").replace("\n", " ")[:300] or "—"
        lines.append("| {} | {} | {} | {} | {} | {} |".format(r["task"], g["id"], g["title"], r["state"], r["attempts"], ev))
    before, rest = text.split(START, 1)
    after = rest.split(END, 1)[1]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    after = re.sub(r"^Last updated:.*$", "Last updated: {} (scripts/status.py)".format(stamp), after, flags=re.M)
    STATUS.write_text(before + START + "\n" + "\n".join(lines) + "\n" + END + after, encoding="utf-8")


def ensure_rows(goals):
    rows = read_rows()
    for g in goals:
        rows.setdefault(g["id"], {"task": g["task"], "goal": g["id"], "title": g["title"], "state": "TODO",
                                  "attempts": 0, "evidence": "—"})
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check"); sub.add_parser("init"); sub.add_parser("next"); sub.add_parser("json")
    s = sub.add_parser("get"); s.add_argument("goal"); s.add_argument("field")
    s = sub.add_parser("set"); s.add_argument("goal"); s.add_argument("state", choices=STATES)
    s.add_argument("--attempts", type=int); s.add_argument("--evidence")
    a = p.parse_args(argv)
    goals = parse_goals()
    by_id = {g["id"]: g for g in goals}
    for g in goals:
        for d in g["deps"]:
            if d not in by_id or goals.index(by_id[d]) >= goals.index(g):
                raise SystemExit("GOALS.md: {} depends on {} which is unknown or not earlier".format(g["id"], d))
    rows = ensure_rows(goals)

    if a.cmd == "check":
        for g in goals:
            print("{} {} deps={} h={} state={}".format(g["id"], g["task"], ",".join(g["deps"]) or "-", g["hours"],
                                                      rows[g["id"]]["state"]))
        print("goals={} hours={}".format(len(goals), sum(g["hours"] for g in goals)))
        return 0
    if a.cmd == "init":
        write_rows(rows, goals)
        return 0
    if a.cmd == "json":
        print(json.dumps([dict(rows[g["id"]], deps=g["deps"], hours=g["hours"]) for g in goals], indent=1))
        return 0
    if a.cmd == "next":
        changed = False
        for g in goals:
            r = rows[g["id"]]
            if r["state"] not in ("TODO", "IN_PROGRESS"):
                continue
            bad = [d for d in g["deps"] if rows[d]["state"] in ("BLOCKED", "SKIPPED")]
            if bad:
                r["state"], r["evidence"], changed = "SKIPPED", "dependency {} not done".format(",".join(bad)), True
                continue
            if all(rows[d]["state"] == "DONE" for d in g["deps"]):
                if changed:
                    write_rows(rows, goals)
                print(g["id"])
                return 0
        if changed:
            write_rows(rows, goals)
        return 0
    if a.goal not in by_id:
        raise SystemExit("unknown goal " + a.goal)
    if a.cmd == "get":
        g, r = by_id[a.goal], rows[a.goal]
        value = {"task": r["task"], "title": g["title"], "state": r["state"], "attempts": r["attempts"],
                 "evidence": r["evidence"], "deps": ",".join(g["deps"]), "hours": g["hours"]}[a.field]
        print(value)
        return 0
    if a.cmd == "set":
        r = rows[a.goal]
        if r["state"] == "DONE" and a.state != "DONE":
            raise SystemExit("refusing to move {} out of DONE".format(a.goal))
        r["state"] = a.state
        if a.attempts is not None:
            r["attempts"] = a.attempts
        if a.evidence is not None:
            r["evidence"] = a.evidence
        write_rows(rows, goals)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
