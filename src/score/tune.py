"""Per-class threshold sweep on a dev run (HARNESS_SPEC §3, ADR-001). Refuses any run that is not all dev (I-9).

    python3 -m src.score.tune --run-id <dev run>      # writes evals/thresholds.json + evals/threshold_sweep.csv
    python3 -m src.score.tune --apply                 # copies τ into workflows/t4-triage.json `0. Config`
    python3 -m src.score.tune --verify                # recomputes from the source run; checks the Config copy

Choices HARNESS_SPEC leaves open: OPEN_QUESTIONS.md Q-26 (6).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.score.score import (CATEGORIES, MANIFEST, PRIORITIES, ROOT, RUNS_DIR, as_float, load_golds, load_run,
                             read_csv, read_json, score_run)

TAUS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.97, 0.99)
NEVER = 1.01                     # no τ reaches the target: always human
POLICY_CLASSES = ("privacy", "other")
TARGET_CATEGORY = 0.95
TARGET_PRIORITY = 0.90
TARGET_P1 = 0.95
MIN_SELECTED = 5
IGNORED_REASON_PREFIXES = ("policy", "threshold")
Z_90 = 1.6448536269514722        # two-sided 90% normal quantile
TUNER_VERSION = "1.0"
SWEEP_HEADER = "kind,class,tau,n_selected,n_correct,precision,coverage,wilson_low_90".split(",")
THRESHOLDS = ROOT / "evals" / "thresholds.json"
SWEEP = ROOT / "evals" / "threshold_sweep.csv"
WORKFLOW = ROOT / "workflows" / "t4-triage.json"
CONFIG_NODE = "0. Config"


class Refused(Exception):
    """The run may not be used for tuning."""


def wilson_low(correct, n, z=Z_90):
    if not n:
        return None
    p = correct / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def eligible(rows):
    """Rows the sweep may use: a parsed category and no rule reason (policy and threshold reasons do not count)."""
    out = []
    for r in rows:
        rule_reasons = [x for x in r.get("_reasons", []) if not x.startswith(IGNORED_REASON_PREFIXES)]
        if r["category_hat"] in CATEGORIES and r["conf_category"] != "" and not rule_reasons:
            out.append(r)
    return out


def sweep(items, kind, cls, target):
    """items: (conf, correct) for tickets predicted in this class. Returns (sweep rows, chosen τ)."""
    rows, chosen = [], NEVER
    for tau in TAUS:
        selected = [ok for conf, ok in items if conf >= tau]
        n, k = len(selected), sum(selected)
        precision = k / n if n else None
        rows.append({"kind": kind, "class": cls, "tau": tau, "n_selected": n, "n_correct": k,
                     "precision": precision, "coverage": n / len(items) if items else None,
                     "wilson_low_90": wilson_low(k, n)})
        if chosen == NEVER and n >= MIN_SELECTED and precision >= target:
            chosen = tau
    return rows, chosen


def tune(rows):
    """(sweep rows, tau_category, tau_priority, global_tau) from scored dev rows."""
    rows = eligible(rows)
    sweep_rows, tau_category, tau_priority = [], {}, {}
    for c in CATEGORIES:
        items = [(as_float(r["conf_category"]), r["category_hat"] == r["category_gold"])
                 for r in rows if r["category_hat"] == c]
        found, tau = sweep(items, "category", c, TARGET_CATEGORY)
        sweep_rows += found
        tau_category[c] = NEVER if c in POLICY_CLASSES else tau
    for p in PRIORITIES:
        items = [(as_float(r["conf_priority"]), r["priority_hat"] == r["priority_gold"])
                 for r in rows if r["priority_hat"] == p and r["conf_priority"] != ""]
        found, tau_priority[p] = sweep(items, "priority", p, TARGET_P1 if p == "P1" else TARGET_PRIORITY)
        sweep_rows += found
    pooled = [(as_float(r["conf_category"]), r["category_hat"] == r["category_gold"])
              for r in rows if r["category_hat"] not in POLICY_CLASSES]
    found, global_tau = sweep(pooled, "global", "all", TARGET_CATEGORY)
    return sweep_rows + found, tau_category, tau_priority, global_tau


def dev_rows(run_id, runs_dir=RUNS_DIR, manifest=MANIFEST):
    run = load_run(run_id, runs_dir)
    rows = score_run(run, load_golds(manifest))
    bad = sorted({r["split"] for r in rows if r["split"] != "dev"})
    if bad or run.summary.get("split", "dev") != "dev" or not rows:
        raise Refused("{}: tuning needs a run whose tickets are all split == dev (I-9); found {}".format(
            run_id, ", ".join(bad) or run.summary.get("split") or "no tickets"))
    return rows


def thresholds_doc(run_id, tau_category, tau_priority, global_tau):
    return {"source_run_id": run_id, "split": "dev",
            "targets": {"category": TARGET_CATEGORY, "priority": TARGET_PRIORITY, "priority_P1": TARGET_P1,
                        "min_selected": MIN_SELECTED},
            "tau_category": tau_category, "tau_priority": tau_priority, "global_tau": global_tau,
            "tuner_version": TUNER_VERSION,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _cell(value):
    return "" if value is None else ("{:.4f}".format(value) if isinstance(value, float) else str(value))


def sweep_lines(sweep_rows):
    return [[_cell(r[k]) if k != "tau" else "{:.2f}".format(r[k]) for k in SWEEP_HEADER] for r in sweep_rows]


def write_outputs(doc, sweep_rows, thresholds_path, sweep_path):
    Path(thresholds_path).parent.mkdir(parents=True, exist_ok=True)
    Path(thresholds_path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    with Path(sweep_path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(SWEEP_HEADER)
        writer.writerows(sweep_lines(sweep_rows))


# ---------------------------------------------------------------- 0. Config
def config_node(workflow):
    return next((n for n in workflow.get("nodes", []) if n.get("name") == CONFIG_NODE), None)


def config_values(node):
    """name -> value of the Set node assignments; JSON strings are parsed."""
    values = {}
    for a in node.get("parameters", {}).get("assignments", {}).get("assignments", []):
        value = a.get("value")
        if isinstance(value, str):
            try:
                value = json.loads(value.lstrip("="))
            except ValueError:
                pass
        values[a.get("name")] = value
    return values


def apply(thresholds_path, workflow_path):
    workflow_path = Path(workflow_path)
    if not workflow_path.exists():
        print("no-op: {} does not exist yet (G7 creates it); thresholds not applied".format(workflow_path))
        return 0
    doc = read_json(thresholds_path)
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    node = config_node(workflow)
    if node is None:
        print("FAIL: {} has no '{}' node".format(workflow_path, CONFIG_NODE))
        return 1
    assignments = node.setdefault("parameters", {}).setdefault("assignments", {}).setdefault("assignments", [])
    for name in ("tau_category", "tau_priority"):
        value = json.dumps(doc[name], sort_keys=True)
        hit = next((a for a in assignments if a.get("name") == name), None)
        if hit is None:
            assignments.append({"id": name, "name": name, "value": value, "type": "object"})
        else:
            hit["value"], hit["type"] = value, "object"
    workflow_path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("applied tau_category and tau_priority from {} to {} '{}'".format(thresholds_path, workflow_path,
                                                                        CONFIG_NODE))
    return 0


def verify(thresholds_path, sweep_path, workflow_path, runs_dir, manifest):
    problems = []
    doc = read_json(thresholds_path)
    if doc is None:
        print("FAIL: {} missing".format(thresholds_path))
        return 1
    if doc.get("split") != "dev":
        problems.append("thresholds split is not dev")
    try:
        sweep_rows, tau_category, tau_priority, global_tau = tune(dev_rows(doc["source_run_id"], runs_dir, manifest))
    except (Refused, FileNotFoundError, ValueError, KeyError) as exc:
        problems.append("cannot recompute: {}".format(exc))
    else:
        for name, want in (("tau_category", tau_category), ("tau_priority", tau_priority), ("global_tau", global_tau)):
            if doc.get(name) != want:
                problems.append("{} differs from a recompute of {}".format(name, doc["source_run_id"]))
        if read_csv(sweep_path) != [dict(zip(SWEEP_HEADER, line)) for line in sweep_lines(sweep_rows)]:
            problems.append("{} differs from a recompute".format(sweep_path))
    if Path(workflow_path).exists():
        node = config_node(json.loads(Path(workflow_path).read_text(encoding="utf-8")))
        values = config_values(node) if node else {}
        for name in ("tau_category", "tau_priority"):
            if values.get(name) != doc.get(name):
                problems.append("{} '{}' {} != thresholds.json".format(workflow_path, CONFIG_NODE, name))
    else:
        print("note: {} does not exist yet; Config copy not checked".format(workflow_path))
    for p in problems:
        print("FAIL: " + p)
    if not problems:
        print("ok: thresholds verified against {}".format(doc.get("source_run_id")))
    return 1 if problems else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-id", help="dev run to tune on")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--thresholds", default=str(THRESHOLDS))
    parser.add_argument("--sweep", default=str(SWEEP))
    parser.add_argument("--workflow", default=str(WORKFLOW))
    parser.add_argument("--runs-dir", default=str(RUNS_DIR))
    parser.add_argument("--manifest", default=str(MANIFEST))
    args = parser.parse_args(argv)
    if args.apply:
        return apply(args.thresholds, args.workflow)
    if args.verify:
        return verify(args.thresholds, args.sweep, args.workflow, args.runs_dir, args.manifest)
    try:
        rows = dev_rows(args.run_id, args.runs_dir, args.manifest)
    except Refused as exc:
        print("REFUSED: {}".format(exc))
        return 2
    sweep_rows, tau_category, tau_priority, global_tau = tune(rows)
    write_outputs(thresholds_doc(args.run_id, tau_category, tau_priority, global_tau), sweep_rows,
                  args.thresholds, args.sweep)
    print("tau_category={} tau_priority={} global_tau={}".format(tau_category, tau_priority, global_tau))
    print("wrote {} and {} ({} sweep rows)".format(args.thresholds, args.sweep, len(sweep_rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
