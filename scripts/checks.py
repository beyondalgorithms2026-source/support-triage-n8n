"""Independent checks used by accept.sh, guard.sh, preflight.sh and overnight.sh.

Python 3.9 stdlib only. Never prints a secret value: secret scans report file, line and variable NAME only.
The overnight worker must not edit this file (scripts/** is write-protected and hash-checked).
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
T2 = ROOT.parent / "rescue-diagnostic-t2"
N8N_LOCAL_COMPOSE = ROOT.parent.parent / "n8n-local" / "docker-compose.yml"

BANNED = re.compile(r"\b(certified|compliant|pentested|secure|production-ready)\b", re.IGNORECASE)
BANNED_EXEMPT = {"AGENTS.md", "CLAUDE.md"}
SECRET_PATTERNS = (
    r"sk-[A-Za-z0-9_-]{20,}", r"sk-proj-", r"ya29\.", r"AIza[0-9A-Za-z_-]{35}", r"Bearer [A-Za-z0-9._-]{20,}",
    r'"(access|refresh)_token"\s*:\s*"[^"]+"', r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"xox[abpr]-[A-Za-z0-9-]{10,}",
)
DEP_FILES = ("package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "pyproject.toml", "setup.py",
             "setup.cfg", "Pipfile", "Pipfile.lock", "poetry.lock")
DEP_DIRS = ("node_modules", ".venv", "venv")
PROTECTED = ("scripts", "GOALS.md", "overnight.conf", "AGENTS.md", "CLAUDE.md")
STDLIB = set("""__future__ abc argparse array ast asyncio atexit base64 binascii bisect calendar codecs collections
concurrent contextlib copy csv dataclasses datetime decimal difflib email enum errno fnmatch fractions functools
getpass glob gzip hashlib heapq hmac html http importlib inspect io ipaddress itertools json locale logging math
mimetypes numbers operator os pathlib platform pprint queue quopri random re secrets select shlex shutil signal
socket socketserver sqlite3 stat statistics string struct subprocess sys tempfile textwrap threading time
traceback types typing unicodedata unittest urllib uuid warnings weakref xml zipfile zlib zoneinfo""".split())
SECRET_NAME = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|_PATH", re.IGNORECASE)
LOCAL_MODULES = {"src", "tests", "scripts", "checks", "status"}

MANIFEST_HEADER = "input_id,split,label_bucket,category,priority,urgency,expect_outcome,gold_path".split(",")
SCORECARD_HEADER = ("run_id,run_phase,input_id,split,label_bucket,category_gold,category_hat,conf_category,"
                    "priority_gold,priority_hat,conf_priority,urgency_gold,urgency_hat,outcome_gold,outcome_hat,"
                    "jira_issue_count,failure_codes,pii_leak,injection_followed,capped,tokens_in,tokens_out,"
                    "usd_cost,duration_ms,notes").split(",")
BUCKETS = {"clean": 104, "hard": 48, "injection": 16, "pii": 12, "duplicate": 12, "malformed": 8}
CATEGORIES = ("billing", "access", "bug", "outage", "howto", "feature", "privacy", "other")
PRIORITIES = ("P1", "P2", "P3", "P4")
URGENCIES = ("high", "medium", "low")
OUTCOMES = ("auto_route", "review", "duplicate_skip", "rejected")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
ALLOWED_EMAIL_DOMAIN = re.compile(r"(^|\.)example\.(com|org|net|invalid)$", re.IGNORECASE)


def fail(msg):
    print("FAIL: " + msg)
    return 1


def ok(msg):
    print("ok: " + msg)
    return 0


def repo_files():
    """Non-ignored files (tracked + untracked) if git exists, else a walk without .git/logs/.env."""
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split("\n")
        return [ROOT / p for p in out if p and (ROOT / p).is_file()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in (".git", "logs", "__pycache__")]
            files += [Path(dirpath) / f for f in filenames if f != ".env"]
        return files


def env_values(path):
    """Return {NAME: value} for non-empty values of length >= 8. Values stay in memory."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if not SECRET_NAME.search(name):
            continue
        if len(value) >= 8 and not re.fullmatch(r"https?://[^\s]+|[0-9.]+", value):
            values[name] = value
    return values


# ---------------------------------------------------------------- guard
def cmd_guard(args):
    rc = 0
    files = repo_files()
    # 1. secret patterns and .env values in non-ignored files
    secrets = {}
    secrets.update(env_values(ROOT / ".env"))
    secrets.update({"T2:" + k: v for k, v in env_values(T2 / ".env").items()})
    compiled = [re.compile(p) for p in SECRET_PATTERNS]
    for path in files:
        if path.name == ".env" or path.suffix in (".png", ".jpg", ".pdf", ".sqlite"):
            continue
        rel = path.relative_to(ROOT)
        if str(rel).startswith("scripts/checks.py") or str(rel).startswith("src/checks/static_checks.py"):
            continue  # pattern definitions
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for c in compiled:
                if c.search(line):
                    rc |= fail("secret pattern in {}:{}".format(rel, n))
            for name, value in secrets.items():
                if value in line:
                    rc |= fail("value of {} found in {}:{}".format(name, rel, n))
    # 2. .env never tracked
    tracked = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if tracked:
        rc |= fail(".env is tracked by git")
    # 3. logs: redact in place, warn only
    logs = ROOT / "logs"
    if logs.is_dir():
        for path in logs.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            new = text
            for name, value in secrets.items():
                new = new.replace(value, "[REDACTED:{}]".format(name))
            if new != text:
                path.write_text(new, encoding="utf-8")
                print("WARN: redacted secret value(s) in {}".format(path.relative_to(ROOT)))
    # 4. no dependency manifests
    for name in DEP_FILES:
        for hit in ROOT.rglob(name):
            if ".git" not in hit.parts:
                rc |= fail("dependency manifest present: {}".format(hit.relative_to(ROOT)))
    for name in DEP_DIRS:
        if (ROOT / name).exists():
            rc |= fail("dependency directory present: {}".format(name))
    for path in files:
        if path.name.startswith("requirements") and path.suffix == ".txt":
            rc |= fail("dependency manifest present: {}".format(path.relative_to(ROOT)))
    # 5. stdlib-only imports
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            rc |= fail("syntax error {}: {}".format(path.relative_to(ROOT), exc))
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name not in STDLIB and name not in LOCAL_MODULES:
                    rc |= fail("non-stdlib import '{}' in {}".format(name, path.relative_to(ROOT)))
    # 6. banned words in prose
    rc |= cmd_banned(argparse.Namespace(paths=[]))
    # 7. outside-folder and protected-file snapshot
    snap = ROOT / "logs" / "outside_snapshot.json"
    if snap.exists():
        before = json.loads(snap.read_text())
        now = snapshot()
        for key, value in before.items():
            if now.get(key) != value:
                rc |= fail("changed since loop start: {}".format(key))
    if rc == 0:
        ok("guard clean")
    return rc


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def snapshot():
    snap = {}
    for item in PROTECTED:
        p = ROOT / item
        paths = sorted(q for q in p.rglob("*") if q.is_file() and "__pycache__" not in q.parts
                       and q.name != ".DS_Store") if p.is_dir() else [p]
        for q in paths:
            snap["protected:" + str(q.relative_to(ROOT))] = _sha(q)
    if (T2 / ".git").exists():
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=T2, capture_output=True, text=True).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=T2, capture_output=True, text=True).stdout
        status = "\n".join(l for l in status.splitlines() if ".DS_Store" not in l)
        snap["outside:t2-head"] = head
        snap["outside:t2-status"] = hashlib.sha256(status.encode()).hexdigest()
    snap["outside:n8n-local-compose"] = _sha(N8N_LOCAL_COMPOSE)
    image = subprocess.run(["docker", "inspect", "-f", "{{.Config.Image}}", "n8n"], capture_output=True, text=True)
    snap["outside:n8n-image"] = image.stdout.strip() if image.returncode == 0 else "unavailable"
    return snap


def cmd_snapshot(args):
    snap = snapshot()
    if args.write:
        Path(args.write).write_text(json.dumps(snap, indent=1, sort_keys=True))
        return ok("snapshot written ({} entries)".format(len(snap)))
    print(json.dumps(snap, indent=1, sort_keys=True))
    return 0


def cmd_protected_changed(args):
    """Exit 1 and list protected files whose hash differs from the loop-start snapshot."""
    snap = ROOT / "logs" / "outside_snapshot.json"
    if not snap.exists():
        return 0
    before = json.loads(snap.read_text())
    now = snapshot()
    changed = [k.split(":", 1)[1] for k, v in before.items() if k.startswith("protected:") and now.get(k) != v]
    for c in changed:
        print(c)
    return 1 if changed else 0


# ---------------------------------------------------------------- prose
def _prose_files(paths):
    if paths:
        return [Path(p) for p in paths]
    out = []
    for path in repo_files():
        rel = path.relative_to(ROOT)
        if rel.parts[0] in ("scripts", "logs", "tests", "src", "THIN-LEDGER-v0.1.md") or path.name in BANNED_EXEMPT:
            continue
        if path.suffix == ".md":
            out.append(path)
    return out


def cmd_banned(args):
    rc = 0
    for path in _prose_files(args.paths):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = BANNED.search(line)
            if m:
                rc |= fail("banned word '{}' in {}:{}".format(m.group(0), path, n))
    return rc


def _words(path):
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.\-/%$]*", text))


def cmd_words(args):
    n = _words(args.file)
    if n > args.max:
        return fail("{} has {} words (max {})".format(args.file, n, args.max))
    return ok("{} has {} words (max {})".format(args.file, n, args.max))


def cmd_headings(args):
    text = Path(args.file).read_text(encoding="utf-8")
    heads = [h.strip() for h in re.findall(r"^#{1,4}\s+(.+)$", text, flags=re.M)]
    pos, rc = -1, 0
    for want in args.heading:
        idx = next((i for i, h in enumerate(heads) if h.lower().startswith(want.lower())), None)
        if idx is None:
            rc |= fail("{}: missing heading '{}'".format(args.file, want))
        elif args.ordered and idx < pos:
            rc |= fail("{}: heading '{}' out of order".format(args.file, want))
        else:
            pos = idx if idx is not None else pos
    return rc or ok("{}: headings present".format(args.file))


def cmd_links(args):
    text = Path(args.file).read_text(encoding="utf-8")
    rc = 0
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
        if re.match(r"[a-z]+://", target) or target.startswith("mailto:"):
            continue
        if not (Path(args.file).parent / target).exists():
            rc |= fail("{}: broken link {}".format(args.file, target))
    return rc or ok("{}: links resolve".format(args.file))


def cmd_contains(args):
    text = Path(args.file).read_text(encoding="utf-8")
    present = args.text.lower() in text.lower()
    if args.absent and present:
        return fail("{} still contains '{}'".format(args.file, args.text))
    if not args.absent and not present:
        return fail("{} lacks '{}'".format(args.file, args.text))
    return ok("{}: contains check".format(args.file))


def cmd_bullets(args):
    n = len(re.findall(r"^\s*[-*] ", Path(args.file).read_text(encoding="utf-8"), flags=re.M))
    return fail("{} has {} bullets (min {})".format(args.file, n, args.min)) if n < args.min else ok("bullets {}".format(n))


def cmd_table_rows(args):
    n = len(re.findall(r"^\|\s*" + re.escape(args.prefix), Path(args.file).read_text(encoding="utf-8"), flags=re.M))
    return fail("{}: {} rows starting '{}' (want {})".format(args.file, n, args.prefix, args.count)) \
        if n != args.count else ok("{} rows".format(n))


def _number_forms(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        v = float(obj)
        for d in range(0, 5):
            out.add(("{:." + str(d) + "f}").format(v))
            out.add(("{:." + str(d) + "f}").format(v * 100))
        out.add(str(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            _number_forms(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _number_forms(value, out)
    elif isinstance(obj, str) and re.fullmatch(r"-?\d+(\.\d+)?", obj):
        _number_forms(float(obj), out)


def cmd_numbers_in_report(args):
    """Every number in the given section of a markdown file must appear in eval_report.json."""
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    forms = set()
    _number_forms(report, forms)
    text = Path(args.file).read_text(encoding="utf-8")
    m = re.search(r"^#{1,4}\s+" + re.escape(args.section) + r".*?$(.*?)(?=^#{1,4}\s|\Z)", text, flags=re.M | re.S)
    if not m:
        return fail("{}: no section '{}'".format(args.file, args.section))
    rc = 0
    for raw in re.findall(r"(?<![\w.-])\$?\d[\d,]*(?:\.\d+)?%?", m.group(1)):
        token = raw.replace("$", "").replace(",", "").rstrip("%")
        if token not in forms and str(float(token)) not in forms:
            rc |= fail("{}: number {} not found in {}".format(args.file, raw, args.report))
    return rc or ok("{}: numbers traced to report".format(args.file))


# ---------------------------------------------------------------- data checks
def cmd_gold(args):
    rc = 0
    manifest = ROOT / "evals" / "inputs" / "manifest.csv"
    if not manifest.exists():
        return fail("missing evals/inputs/manifest.csv")
    with manifest.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [dict(zip(header, r)) for r in reader]
    if header != MANIFEST_HEADER:
        rc |= fail("manifest header != frozen header")
    if len(rows) != 200:
        rc |= fail("manifest has {} rows, want 200".format(len(rows)))
    ids = [r["input_id"] for r in rows]
    if ids != ["t4-{:03d}".format(i) for i in range(1, 201)]:
        rc |= fail("input_ids must be t4-001..t4-200 in order")
    counts = {b: sum(1 for r in rows if r["label_bucket"] == b) for b in BUCKETS}
    if counts != BUCKETS:
        rc |= fail("bucket counts {} != {}".format(counts, BUCKETS))
    splits = {s: sum(1 for r in rows if r["split"] == s) for s in ("dev", "test")}
    if splits != {"dev": 100, "test": 100}:
        rc |= fail("split counts {}".format(splits))
    for c in CATEGORIES:
        n = sum(1 for r in rows if r["category"] == c)
        if n < 20:
            rc |= fail("category {} has {} tickets (< 20)".format(c, n))
    position = {r["input_id"]: i for i, r in enumerate(rows)}
    split_of = {r["input_id"]: r["split"] for r in rows}
    for r in rows:
        if r["category"] not in CATEGORIES or r["priority"] not in PRIORITIES or r["urgency"] not in URGENCIES \
                or r["expect_outcome"] not in OUTCOMES:
            rc |= fail("{}: label outside enum".format(r["input_id"]))
        gold_path = ROOT / r["gold_path"]
        if not gold_path.exists():
            rc |= fail("{}: missing {}".format(r["input_id"], r["gold_path"]))
            continue
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        if gold.get("synthetic") is not True:
            rc |= fail("{}: synthetic != true".format(r["input_id"]))
        if gold.get("input_id") != r["input_id"] or gold.get("split") != r["split"]:
            rc |= fail("{}: gold/manifest mismatch".format(r["input_id"]))
        exp = gold.get("expected") or {}
        if (exp.get("category"), exp.get("priority"), exp.get("urgency")) != (r["category"], r["priority"], r["urgency"]):
            rc |= fail("{}: expected labels differ from manifest".format(r["input_id"]))
        ticket = gold.get("ticket") or {}
        blob = json.dumps(ticket)
        for domain in EMAIL_RE.findall(blob):
            if not ALLOWED_EMAIL_DOMAIN.search(domain):
                rc |= fail("{}: email domain {} not allowed".format(r["input_id"], domain))
        dup = gold.get("duplicate_of")
        if dup:
            if dup not in position or position[dup] >= position[r["input_id"]] or split_of[dup] != r["split"]:
                rc |= fail("{}: duplicate_of {} must be earlier and in the same split".format(r["input_id"], dup))
        for key in ("label_notes", "expect_outcome", "must_review", "dedupe_key", "pii", "injection", "fault"):
            if key not in gold:
                rc |= fail("{}: gold lacks '{}'".format(r["input_id"], key))
    return rc or ok("golden set structure (200 tickets)")


def cmd_csv_rows(args):
    with open(args.file, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        n = sum(1 for _ in reader)
    if args.header == "scorecard" and header != SCORECARD_HEADER:
        return fail("{}: header != frozen scorecard header".format(args.file))
    if n != args.rows:
        return fail("{}: {} data rows, want {}".format(args.file, n, args.rows))
    return ok("{}: {} rows".format(args.file, n))


def cmd_spend(args):
    """Sum usd in evals/cost_ledger.csv and compare with PROJECT_LLM_USD_CAP from .env (cap value only)."""
    cap = None
    for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
        if line.startswith("PROJECT_LLM_USD_CAP="):
            cap = float(line.split("=", 1)[1].strip() or "nan")
    ledger = ROOT / "evals" / "cost_ledger.csv"
    total = 0.0
    if ledger.exists():
        with ledger.open(newline="", encoding="utf-8") as f:
            total = sum(float(r.get("usd") or 0) for r in csv.DictReader(f))
    print("project LLM spend usd={:.4f} cap={}".format(total, cap))
    if cap is None or cap != cap:
        return fail("PROJECT_LLM_USD_CAP not set")
    return fail("spend over cap") if total > cap else ok("spend within cap")


def cmd_env_names(args):
    """Check .env has each NAME with a non-empty value. Prints names only."""
    path = ROOT / ".env"
    if not path.exists():
        return fail(".env missing (run: python3 scripts/init_env.py)")
    present = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            present[k.strip()] = bool(v.strip().strip('"').strip("'"))
    rc = 0
    for name in args.names:
        if not present.get(name):
            rc |= fail(".env: {} missing or empty".format(name))
    return rc or ok(".env: {} names present".format(len(args.names)))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("guard")
    s = sub.add_parser("snapshot"); s.add_argument("--write")
    sub.add_parser("protected-changed")
    s = sub.add_parser("banned"); s.add_argument("paths", nargs="*")
    s = sub.add_parser("words"); s.add_argument("file"); s.add_argument("max", type=int)
    s = sub.add_parser("headings"); s.add_argument("file"); s.add_argument("heading", nargs="+"); s.add_argument("--ordered", action="store_true")
    s = sub.add_parser("links"); s.add_argument("file")
    s = sub.add_parser("contains"); s.add_argument("file"); s.add_argument("text"); s.add_argument("--absent", action="store_true")
    s = sub.add_parser("bullets"); s.add_argument("file"); s.add_argument("min", type=int)
    s = sub.add_parser("table-rows"); s.add_argument("file"); s.add_argument("prefix"); s.add_argument("count", type=int)
    s = sub.add_parser("numbers-in-report"); s.add_argument("file"); s.add_argument("report"); s.add_argument("--section", default="Results")
    sub.add_parser("gold")
    s = sub.add_parser("csv-rows"); s.add_argument("file"); s.add_argument("rows", type=int); s.add_argument("--header", default="")
    sub.add_parser("spend")
    s = sub.add_parser("env-names"); s.add_argument("names", nargs="+")
    args = p.parse_args(argv)
    fn = {"guard": cmd_guard, "snapshot": cmd_snapshot, "protected-changed": cmd_protected_changed,
          "banned": cmd_banned, "words": cmd_words, "headings": cmd_headings, "links": cmd_links,
          "contains": cmd_contains, "bullets": cmd_bullets, "table-rows": cmd_table_rows,
          "numbers-in-report": cmd_numbers_in_report, "gold": cmd_gold, "csv-rows": cmd_csv_rows,
          "spend": cmd_spend, "env-names": cmd_env_names}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
