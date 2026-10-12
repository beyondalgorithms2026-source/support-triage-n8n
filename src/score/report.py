"""Generate evals/eval_report.json, security_findings.{json,md} and SHA256SUMS (HARNESS_SPEC §6). Never edit by hand.

    python3 -m src.score.report --run-id <test run> [--attack-run-id <attack run>]
    python3 -m src.score.report --verify             # SHA256SUMS hold; a rebuild from the recorded inputs is equal
    python3 -m src.score.report --verify-findings    # every number in evals/findings.md is in eval_report.json

eval_report.json holds no timestamp, so --verify can rebuild it and compare. Definitions: OPEN_QUESTIONS.md Q-26.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from src.score.score import (MANIFEST, PRIORITIES, ROOT, RUNS_DIR, as_float, cost, failure_counts, load_golds,
                             load_run, quality, read_json, routing, run_facts, score_run)
from src.score.tune import NEVER, POLICY_CLASSES, eligible

SCHEMA_VERSION = "1.0"
OUT_DIR = ROOT / "evals"
HASHED = ("eval_report.json", "scorecard.csv", "thresholds.json", "security_findings.json")
PROJECTION_TICKETS = 1000
ZERO_TOLERANCE = ("unsafe_auto", "duplicate_issue", "pii_leak", "silent_drop", "audit_gap")
# HARNESS_SPEC §2 proposed targets (OPEN_QUESTIONS Q-11): name, (section, key), pass at, warn at, higher is better.
TARGETS = (
    ("auto_route_precision", ("routing", "auto_precision"), 0.95, 0.90, True),
    ("pct_routed_to_human", ("routing", "pct_human"), 0.40, 0.60, False),
    ("p1_recall", ("quality", "priority", "p1_recall"), 0.90, 0.75, True),
    ("usd_per_1k_tickets", ("cost", "usd_per_1k_tickets"), 1.00, 2.00, False),
    ("latency_ms_p95", ("operations", "latency_ms_p95"), 10000, 20000, False),
)
# docs/SECURITY_CONTROLS.md §2: id, attack, controls, OWASP.
SEC_CATALOGUE = (
    ("SEC-01", "Direct injection: force category/priority", "C-6, C-9, C-14", "LLM01, ASI01"),
    ("SEC-02", "Direct injection: skip review", "C-6, C-15", "LLM01, ASI09"),
    ("SEC-03", "Indirect injection in quoted forwarded email", "C-7, C-6", "LLM01, ASI01"),
    ("SEC-04", "Indirect injection in signature / HTML comment / attachment file name", "C-6, C-2", "LLM01"),
    ("SEC-05", "Encoded injection", "C-6", "LLM01"),
    ("SEC-06", "Slack broadcast / link injection", "C-20", "LLM10, ASI02"),
    ("SEC-07", "Jira field injection", "C-19, C-17", "LLM10, LLM03"),
    ("SEC-08", "PII leak to model", "C-5", "LLM02"),
    ("SEC-09", "PII exfil via instruction", "C-5, C-9, I-11", "LLM02, ASI01"),
    ("SEC-10", "Oversized input", "C-2", "LLM06"),
    ("SEC-11", "Malformed input", "C-2, C-3, C-25", "LLM06"),
    ("SEC-12", "Cost blow-up: burst", "C-8", "LLM06"),
    ("SEC-13", "Cost blow-up: cap reset by run id", "C-8 (ADR-007)", "LLM06"),
    ("SEC-14", "Duplicate write: webhook retry", "C-18", "ASI08"),
    ("SEC-15", "Duplicate write: lost Jira response", "C-18", "ASI08"),
    ("SEC-16", "Duplicate write: lost link row", "C-18", "ASI08"),
    ("SEC-17", "Duplicate write: search lag", "C-18", "ASI08"),
    ("SEC-18", "Unauthenticated / wrong token", "C-1", "LLM06, ASI03"),
    ("SEC-19", "Privilege boundary", "C-17", "LLM03, ASI02, ASI03"),
    ("SEC-20", "Secrets in artifacts", "I-3", "LLM02"),
)
_NUMBER = re.compile(r"(?<![\w.-])\$?\d[\d,]*(?:\.\d+)?%?")


def rel(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def resolve(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def rounded(obj):
    """Floats to 6 significant digits, recursively; JSON round trip so a rebuild compares equal to the file."""
    def walk(value):
        if isinstance(value, float):
            return float("{:.6g}".format(value))
        if isinstance(value, dict):
            return {str(k): walk(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [walk(v) for v in value]
        return value
    return json.loads(json.dumps(walk(obj)))


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- eval report
def simulate(rows, tau_category, tau_priority):
    """Auto-route the eligible rows with the given category τ function and per-level priority τ."""
    pool = eligible(rows)
    auto = [r for r in pool if r["category_hat"] not in POLICY_CLASSES and r["priority_hat"] in PRIORITIES
            and as_float(r["conf_category"]) >= tau_category(r["category_hat"])
            and as_float(r["conf_priority"]) >= tau_priority.get(r["priority_hat"], NEVER)]
    correct = [r for r in auto if r["category_hat"] == r["category_gold"] and r["priority_hat"] == r["priority_gold"]]
    return {"eligible": len(pool), "auto_routed": len(auto),
            "coverage": len(auto) / len(pool) if pool else None,
            "precision": len(correct) / len(auto) if auto else None}


def threshold_comparison(rows, thresholds):
    """Per-class against one global category τ at the same targets (ADR-001 evidence)."""
    if not thresholds:
        return None
    tau_priority = thresholds.get("tau_priority") or {}
    return {
        "source_run_id": thresholds.get("source_run_id"),
        "per_class": simulate(rows, lambda c: thresholds["tau_category"].get(c, NEVER), tau_priority),
        "global": simulate(rows, lambda c: thresholds.get("global_tau", NEVER), tau_priority),
    }


def grade(value, pass_at, warn_at, higher_is_better):
    if value is None:
        return "no_data"
    if higher_is_better:
        return "pass" if value >= pass_at else ("warn" if value >= warn_at else "breach")
    return "pass" if value <= pass_at else ("warn" if value <= warn_at else "breach")


def metric_status(report):
    status = {}
    for name, path, pass_at, warn_at, higher in TARGETS:
        value = report
        for key in path:
            value = (value or {}).get(key)
        status[name] = {"value": value, "status": grade(value, pass_at, warn_at, higher)}
    for code in ZERO_TOLERANCE:
        n = report["operations"]["failure_codes"][code]
        status[code] = {"value": n, "status": "pass" if n == 0 else "breach"}
    return status


def limitations(rows):
    out = []
    for code, n in failure_counts(rows)[0].items():
        if n:
            ids = [r["input_id"] for r in rows if code in r["failure_codes"].split("|")]
            out.append({"statement": "Failure code {} fired on {} ticket(s).".format(code, n), "input_ids": ids})
    out.append({"statement": "Thresholds rest on a small dev split; Wilson lower bounds are reported, not used to "
                             "choose (HARNESS_SPEC §3).", "input_ids": []})
    return out


def build_report(run_id, runs_dir=RUNS_DIR, manifest=MANIFEST, thresholds_path=OUT_DIR / "thresholds.json",
                 attack_run_id=None):
    run = load_run(run_id, runs_dir)
    golds = load_golds(manifest)
    rows = score_run(run, golds)
    thresholds = read_json(thresholds_path)
    facts, costs = run_facts(run), cost(rows)
    totals, by_bucket = failure_counts(rows)
    first_gold = golds[rows[0]["input_id"]] if rows else {}
    report = {
        "schema_version": SCHEMA_VERSION,
        "evidence_status": "candidate",
        "configuration": {
            "model": run.summary.get("model"), "prompt_sha256": run.summary.get("prompt_sha256"),
            "workflow_sha256": run.summary.get("workflow_sha256"),
            "thresholds_sha256": sha256_file(thresholds_path) if Path(thresholds_path).exists() else None,
            "n8n_version": run.summary.get("n8n_version"),
            "generator_version": (first_gold.get("generator") or {}).get("version"),
            "run_ids": [run_id] + ([attack_run_id] if attack_run_id else []),
        },
        "inputs": {"run_id": run_id, "attack_run_id": attack_run_id, "runs_dir": rel(runs_dir),
                   "manifest": rel(manifest), "thresholds": rel(thresholds_path)},
        "quality": quality(rows),
        "routing": dict(routing(rows), threshold_comparison=threshold_comparison(rows, thresholds)),
        "operations": {
            "max_issues_per_dedupe_key": facts["max_issues_per_dedupe_key"],
            "new_jira_issues_pass_b": facts["new_jira_issues_pass_b"],
            "llm_calls_pass_b": facts["llm_calls_pass_b"],
            "pii_leaks_by_target": dict(sorted(Counter(t for r in rows for t in r["_leaks"]).items())),
            "failure_codes": totals, "failure_codes_by_bucket": by_bucket,
            "latency_ms_p50": costs["latency_ms_p50"], "latency_ms_p95": costs["latency_ms_p95"],
        },
        "cost": {
            "usd_run": facts["usd_run"], "llm_calls": facts["llm_calls"], "tokens_in": facts["tokens_in"],
            "tokens_out": facts["tokens_out"], "usd_per_ticket_mean": costs["usd_per_ticket_mean"],
            "usd_per_ticket_p95": costs["usd_per_ticket_p95"], "tokens_per_ticket_mean": costs["tokens_per_ticket_mean"],
            "tokens_per_ticket_p95": costs["tokens_per_ticket_p95"], "usd_per_1k_tickets": costs["usd_per_1k_tickets"],
            "projection_tickets": PROJECTION_TICKETS,
        },
        "limitations": limitations(rows),
    }
    report = rounded(report)
    report["metric_status"] = metric_status(report)
    return report


# ---------------------------------------------------------------- security findings
def security_findings(attack_run_id=None, runs_dir=RUNS_DIR):
    results = {}
    if attack_run_id:
        data = read_json(Path(runs_dir) / attack_run_id / "attack_results.json", {}) or {}
        results = {r.get("id"): r for r in data.get("results", [])}
    findings = []
    for sec_id, attack, controls, owasp in SEC_CATALOGUE:
        r = results.get(sec_id) or {}
        findings.append({"id": sec_id, "attack": attack, "result": r.get("result", "not_run"), "controls": controls,
                         "owasp": owasp, "evidence": r.get("evidence", ""), "input_ids": r.get("input_ids", []),
                         "residual": r.get("residual") or ("not run" if not r else "not stated by the attack run")})
    return {"schema_version": SCHEMA_VERSION, "attack_run_id": attack_run_id, "findings": findings}


def render_findings_md(doc):
    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ")
    lines = ["# Security findings", "",
             "Generated by `python3 -m src.score.report` from attack run `{}`. Do not edit by hand.".format(
                 doc["attack_run_id"] or "none"),
             "Result is filled only from run evidence; `not_run` means no evidence yet.", "",
             "| ID | Attack | Result | Control | Residual risk |", "|---|---|---|---|---|"]
    lines += ["| {} | {} | {} | {} | {} |".format(f["id"], cell(f["attack"]), cell(f["result"]), cell(f["controls"]),
                                                  cell(f["residual"])) for f in doc["findings"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- write and verify
def write_all(out_dir, run_id, runs_dir, manifest, thresholds_path, attack_run_id):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(run_id, runs_dir, manifest, thresholds_path, attack_run_id)
    findings = security_findings(attack_run_id, runs_dir)
    (out_dir / "eval_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "security_findings.json").write_text(json.dumps(findings, indent=2) + "\n", encoding="utf-8")
    (out_dir / "security_findings.md").write_text(render_findings_md(findings), encoding="utf-8")
    sums = ["{}  {}".format(sha256_file(out_dir / name), name) for name in HASHED if (out_dir / name).exists()]
    (out_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return report


def sums_problems(out_dir):
    out_dir, problems, listed = Path(out_dir), [], set()
    path = out_dir / "SHA256SUMS"
    if not path.exists():
        return ["SHA256SUMS missing"]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        listed.add(name.strip())
        target = out_dir / name.strip()
        if not target.exists():
            problems.append("{} listed in SHA256SUMS but missing".format(name.strip()))
        elif sha256_file(target) != digest:
            problems.append("{} hash differs from SHA256SUMS".format(name.strip()))
    problems += ["{} exists but is not in SHA256SUMS".format(n) for n in HASHED
                 if (out_dir / n).exists() and n not in listed]
    return problems


def verify(out_dir):
    out_dir = Path(out_dir)
    report = read_json(out_dir / "eval_report.json")
    if report is None:
        return ["eval_report.json missing"]
    problems = sums_problems(out_dir)
    inputs = report.get("inputs") or {}
    try:
        rebuilt = build_report(inputs["run_id"], resolve(inputs["runs_dir"]), resolve(inputs["manifest"]),
                               resolve(inputs["thresholds"]), inputs.get("attack_run_id"))
    except (KeyError, FileNotFoundError, ValueError) as exc:
        return problems + ["cannot rebuild eval_report.json: {}".format(exc)]
    if rebuilt != report:
        problems.append("eval_report.json differs from a rebuild of its recorded inputs")
    findings = security_findings(inputs.get("attack_run_id"), resolve(inputs["runs_dir"]))
    if read_json(out_dir / "security_findings.json") != rounded(findings):
        problems.append("security_findings.json differs from a rebuild")
    md = out_dir / "security_findings.md"
    if not md.exists() or md.read_text(encoding="utf-8") != render_findings_md(findings):
        problems.append("security_findings.md differs from a rebuild")
    return problems


def number_forms(obj, out=None):
    """Every text form a report number may take in prose: 0–4 decimals, and ×100 for percentages."""
    out = set() if out is None else out
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        for d in range(5):
            out.add("{:.{}f}".format(obj, d))
            out.add("{:.{}f}".format(obj * 100, d))
        out.add(str(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            number_forms(value, out)
    elif isinstance(obj, list):
        for value in obj:
            number_forms(value, out)
    elif isinstance(obj, str) and re.fullmatch(r"-?\d+(\.\d+)?", obj):
        number_forms(float(obj), out)
    return out


def findings_numbers(text):
    """Numbers in prose: code, link targets, headings and the owner's Trace notes section are left out."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^#{1,4}\s+Trace notes.*?(?=^#{1,4}\s|\Z)", " ", text, flags=re.M | re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = "\n".join(line for line in text.splitlines() if not re.match(r"^#{1,6}\s", line))
    return _NUMBER.findall(text)


def verify_findings(findings_path, report_path):
    if not Path(findings_path).exists():
        return ["{} missing".format(findings_path)]
    report = read_json(report_path)
    if report is None:
        return ["{} missing".format(report_path)]
    forms = number_forms(report)
    problems = []
    for raw in findings_numbers(Path(findings_path).read_text(encoding="utf-8")):
        token = raw.replace("$", "").replace(",", "").rstrip("%")
        if token not in forms and str(float(token)) not in forms:
            problems.append("number {} in {} is not in {}".format(raw, findings_path, report_path))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-id", help="the scored (test) run")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--verify-findings", action="store_true")
    parser.add_argument("--attack-run-id")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--runs-dir", default=str(RUNS_DIR))
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--thresholds", help="default: <out-dir>/thresholds.json")
    parser.add_argument("--findings", help="default: <out-dir>/findings.md")
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    if args.verify or args.verify_findings:
        problems = verify(out_dir) if args.verify else verify_findings(
            args.findings or out_dir / "findings.md", out_dir / "eval_report.json")
        for p in problems:
            print("FAIL: " + p)
        if not problems:
            print("ok: {} verified".format("report" if args.verify else "findings numbers"))
        return 1 if problems else 0
    report = write_all(out_dir, args.run_id, args.runs_dir, args.manifest,
                       args.thresholds or out_dir / "thresholds.json", args.attack_run_id)
    status = {k: v["status"] for k, v in report["metric_status"].items()}
    print("wrote eval_report.json, security_findings.json/.md, SHA256SUMS in {}; metric_status {}".format(
        out_dir, status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
