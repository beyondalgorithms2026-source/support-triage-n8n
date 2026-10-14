"""Set up and replay golden tickets against local n8n without its public API (ported from T2 `LocalN8n`).

    python3 -m src.replay.run setup
    python3 -m src.replay.run run --phase slice --split dev --limit 10 [--ids t4-001 …] [--passes A|AB]
        [--force-fault t4-007:jira:503] [--config-override run_usd_cap=0.10]

`setup` builds the five n8n credentials in memory from `.env` and imports them through `docker exec -i … --input=
/dev/stdin`. `run` substitutes placeholders in memory, imports and publishes the workflow (unpublish in `finally`),
starts a fresh sink for the run, submits tickets one at a time (I-7), and reads each execution from n8n SQLite in
read-only mode. It writes `evals/runs/<run_id>/` (trace.jsonl, sink/, static_checks.json, summary.json) and one
`evals/cost_ledger.csv` row. Caps: refuses to start when the project cap would be passed; stops submitting when the
run passes `RUN_USD_CAP`. Nothing here prints or writes a credential, token, webhook path or `.env` value.
`--phase attack` (G11) adds isolated segments, the SEC-18 probe, the SEC-20 scan and `attack_results.json`
(`src/replay/attacks.py`); the cap counts the spend of every segment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.checks.static_checks import check_file
from src.replay import attacks
from src.score.score import is_llm_node, read_csv
from src.sink.server import FAULTS, make_server

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "workflows" / "t4-triage.json"
HANDLER = ROOT / "workflows" / "t4-error-handler.json"
MANIFEST = ROOT / "evals" / "inputs" / "manifest.csv"
RUNS_DIR = ROOT / "evals" / "runs"
COST_LEDGER = ROOT / "evals" / "cost_ledger.csv"
THRESHOLDS = ROOT / "evals" / "thresholds.json"
TIMEOUT_SECONDS = 180
CONFIG_NODE = "0. Config"
LEDGER_HEADER = ("run_id,run_phase,target,started_utc,ended_utc,model,llm_calls,tokens_in,tokens_out,usd,"
                 "run_usd_cap,capped_inputs,tickets,usd_per_1k_tickets").split(",")
# Phase -> (split, passes) defaults; the same table as src/score/check_run.py PHASES and HARNESS_SPEC §4.
PHASES = {"slice": ("dev", "A"), "smoke": ("dev", "AB"), "dev": ("dev", "A"), "test": ("test", "AB"),
          "attack": (None, "A")}
CREDENTIAL_IDS = {"t4-llm": "t4LlmBearerKey01", "t4-webhook-auth": "t4WebhookAuth001",
                  "t4-sink-auth": "t4SinkAuth000001", "t4-jira": "t4JiraBasic00001", "t4-slack": "t4SlackBearer001"}
PLACEHOLDERS = {"__SINK_BASE_URL__": "SINK_BASE_URL", "__JIRA_BASE_URL__": "JIRA_BASE_URL",
                "__SLACK_BASE_URL__": "SLACK_BASE_URL", "__WEBHOOK_PATH__": "T4_WEBHOOK_PATH"}
SETUP_ENV = ("OPENAI_API_KEY", "T4_WEBHOOK_TOKEN", "SINK_TOKEN", "JIRA_SANDBOX_EMAIL", "JIRA_SANDBOX_API_TOKEN",
             "SLACK_SANDBOX_BOT_TOKEN")
RUN_ENV = ("N8N_BASE_URL", "T4_WEBHOOK_TOKEN", "T4_WEBHOOK_PATH", "SINK_TOKEN", "SINK_BASE_URL", "JIRA_BASE_URL",
           "SLACK_BASE_URL", "JIRA_SANDBOX_EMAIL", "JIRA_SANDBOX_API_TOKEN", "SLACK_SANDBOX_BOT_TOKEN", "RUN_USD_CAP",
           "PROJECT_LLM_USD_CAP")
# Values scrubbed from every trace string (the webhook node output holds request headers, T2 R-3).
SECRET_ENV = ("OPENAI_API_KEY", "T4_WEBHOOK_TOKEN", "T4_WEBHOOK_PATH", "SINK_TOKEN", "JIRA_SANDBOX_EMAIL",
              "JIRA_SANDBOX_API_TOKEN", "SLACK_SANDBOX_BOT_TOKEN")
# Config key -> env name that must hold the same value (ARCHITECTURE §5.1).
CONFIG_ENV = {"llm_price_in_per_mtok": "LLM_PRICE_IN_PER_MTOK", "llm_price_out_per_mtok": "LLM_PRICE_OUT_PER_MTOK",
              "run_usd_cap": "RUN_USD_CAP", "daily_usd_cap": "DAILY_USD_CAP"}
STAGES = (("H1", "intake"), ("H2", "intake"), ("H3", "intake"), ("H4", "intake"), ("H5", "classify"),
          ("H6", "classify"), ("H7", "classify"), ("H8", "classify"), ("H9", "validate"), ("H10", "decide"),
          ("H11", "act"), ("H12", "act"), ("H12r", "act"), ("H12b", "act"), ("H13", "act"), ("H14", "act"),
          ("H15", "approve"), ("H15s", "approve"), ("H16", "record"), ("H16r", "record"), ("E", "record"),
          ("W0", "intake"), ("W1", "intake"), ("0.", "intake"))


# ---------------------------------------------------------------- small helpers
def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stage_for(node):
    """METHOD stage label from the node-name prefix (ARCHITECTURE §4); unknown nodes are `record`."""
    first = str(node or "").split(" ", 1)[0]
    return dict(STAGES).get(first, "record")


def sha256_file(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def git_short_sha():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.strip()
        return out or "nogit"
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def load_env_file(path):
    """Copy KEY=value lines into os.environ without overriding values already set. Values stay in memory."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_env(env, names):
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise ValueError("not set in .env: " + ", ".join(missing))


def scrubber(env):
    """Return f(value) that replaces every secret env value in nested strings with [REDACTED:<NAME>]."""
    secrets = sorted(((name, env[name]) for name in SECRET_ENV if len(env.get(name) or "") >= 4),
                     key=lambda pair: -len(pair[1]))

    def scrub(value):
        if isinstance(value, str):
            for name, secret in secrets:
                value = value.replace(secret, "[REDACTED:{}]".format(name))
            return value
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value
    return scrub


def request_json(method, url, token, body=None, timeout=10):
    """One sink request. Errors are explicit; requests are never retried."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"X-Sink-Token": token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as error:
        try:
            return error.code, json.loads(error.read().decode("utf-8") or "{}")
        except ValueError:
            return error.code, {}
    except URLError as error:
        raise RuntimeError("sink request failed") from error


def submit(webhook_url, token, run_id, gold, timeout=TIMEOUT_SECONDS):
    """POST the gold `ticket` object to the webhook (ARCHITECTURE §6.1). Returns the HTTP status."""
    data = json.dumps(gold["ticket"], ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-T4-Token": token, "X-Replay-Run-Id": run_id,
               "X-Replay-Input-Id": gold["input_id"]}
    try:
        with urlopen(Request(webhook_url, data=data, headers=headers, method="POST"), timeout=timeout) as response:
            return response.status
    except HTTPError as error:
        return error.code
    except URLError as error:
        raise RuntimeError("webhook submission failed") from error


# ---------------------------------------------------------------- credentials and workflow (in memory)
def credential_payload(env):
    """The five frozen credentials (HANDOFF.md), built in memory from the environment; never written to disk."""
    def header(name, header_name, value):
        return {"id": CREDENTIAL_IDS[name], "name": name, "type": "httpHeaderAuth",
                "data": {"name": header_name, "value": value}}
    return [header("t4-llm", "Authorization", "Bearer " + env["OPENAI_API_KEY"]),
            header("t4-webhook-auth", "X-T4-Token", env["T4_WEBHOOK_TOKEN"]),
            header("t4-sink-auth", "X-Sink-Token", env["SINK_TOKEN"]),
            {"id": CREDENTIAL_IDS["t4-jira"], "name": "t4-jira", "type": "httpBasicAuth",
             "data": {"user": env["JIRA_SANDBOX_EMAIL"], "password": env["JIRA_SANDBOX_API_TOKEN"]}},
            header("t4-slack", "Authorization", "Bearer " + env["SLACK_SANDBOX_BOT_TOKEN"])]


def config_assignments(workflow):
    """The `0. Config` Set node's assignment list (the same place `tune.py --apply` writes τ)."""
    for node in workflow.get("nodes", []):
        if node.get("name") == CONFIG_NODE:
            return node["parameters"]["assignments"]["assignments"]
    return []


def config_values(workflow):
    return {a["name"]: a.get("value") for a in config_assignments(workflow)}


def apply_overrides(workflow, overrides):
    """`key=value` pairs into `0. Config` of an in-memory copy. Unknown keys are an error (no silent typos)."""
    workflow = json.loads(json.dumps(workflow))
    by_name = {a["name"]: a for a in config_assignments(workflow)}
    for item in overrides or ():
        key, sep, raw = item.partition("=")
        if not sep or key not in by_name:
            raise ValueError("config override {!r}: key not in {}".format(key, CONFIG_NODE))
        old = by_name[key].get("value")
        if isinstance(old, str):
            by_name[key]["value"] = raw
        else:
            try:
                by_name[key]["value"] = json.loads(raw)
            except ValueError as error:
                raise ValueError("config override {!r}: value is not JSON".format(key)) from error
    return workflow


def bind_credentials(workflow, ids):
    """Set each node credential's id from its name (workflow JSON names credentials only, I-10)."""
    workflow = json.loads(json.dumps(workflow))
    for node in workflow.get("nodes", []):
        for ref in (node.get("credentials") or {}).values():
            if isinstance(ref, dict) and ref.get("name") in ids:
                ref["id"] = ids[ref["name"]]
    return workflow


def substitute(workflow, env):
    """Replace the four placeholders (I-10) in memory. The committed file is never written."""
    text = json.dumps(workflow, ensure_ascii=False)
    for placeholder, name in PLACEHOLDERS.items():
        if placeholder in text:
            require_env(env, (name,))
            text = text.replace(placeholder, json.dumps(env[name].rstrip("/"))[1:-1])
    return json.loads(text)


def prompt_sha256(workflow):
    """sha256 of the committed H6 node parameters (the prompt and request body), or None before G7."""
    for node in workflow.get("nodes", []):
        if is_llm_node(node.get("name")):
            return hashlib.sha256(json.dumps(node.get("parameters"), sort_keys=True,
                                             ensure_ascii=False).encode("utf-8")).hexdigest()
    return None


def parse_fault(spec):
    """`<input_id>:<target>:<mode>[:A|B]` -> (input_id, fault body). The target may hold a colon (sink:jira_links)."""
    parts = spec.split(":")
    run_pass = parts.pop() if len(parts) >= 4 and parts[-1] in ("A", "B") else "A"
    if len(parts) < 3:
        raise ValueError("force-fault must be <input_id>:<target>:<mode>[:A|B]")
    input_id, target, mode = parts[0], ":".join(parts[1:-1]), parts[-1]
    if (target, mode) not in FAULTS:
        raise ValueError("unknown fault {}:{}".format(target, mode))
    return input_id, {"target": target, "mode": mode, "pass": run_pass}


# ---------------------------------------------------------------- tickets
def load_manifest(manifest):
    with open(manifest, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def select_tickets(rows, phase, split=None, ids=None, limit=None):
    """Manifest rows for this run, in manifest order (a duplicate always follows its original)."""
    want_split = PHASES[phase][0]
    if split and want_split and split != want_split:
        raise ValueError("phase {} runs on split {} only (I-9)".format(phase, want_split))
    split = split or want_split
    wanted = [i for item in ids or () for i in item.replace(",", " ").split()]
    known = {row["input_id"]: row for row in rows}
    unknown = [i for i in wanted if i not in known]
    if unknown:
        raise ValueError("ids not in manifest: " + ", ".join(unknown))
    chosen = [row for row in rows if (not wanted or row["input_id"] in wanted)]
    outside = [row["input_id"] for row in chosen if split and row["split"] != split]
    if wanted and outside:
        raise ValueError("ids outside split {}: {}".format(split, ", ".join(outside)))
    chosen = [row for row in chosen if not split or row["split"] == split]
    if limit is not None:
        chosen = chosen[:limit]
    if not chosen:
        raise ValueError("no tickets selected")
    return chosen


def read_gold(row):
    path = Path(row["gold_path"])
    return json.loads((path if path.is_absolute() else ROOT / path).read_text(encoding="utf-8"))


def project_spend(cost_ledger):
    return sum(float(row.get("usd") or 0) for row in read_csv(cost_ledger))


def ledger_usd(sink_dir, run_id):
    """Spend the workflow itself recorded for this run (sink `ledger` table, H7). SEC-13 sends `<run_id>-rNN`."""
    return sum(float(row.get("usd") or 0) for row in read_csv(Path(sink_dir) / "ledger.csv")
               if row.get("run_id") == run_id or str(row.get("run_id") or "").startswith(run_id + "-r"))


# ---------------------------------------------------------------- n8n (CLI + read-only SQLite)
class LocalN8n:
    """CLI lifecycle and read-only SQLite execution reader for the local container (T2 port)."""

    def __init__(self, db_path=None, container="n8n", command=subprocess.run, sleeper=time.sleep):
        self.db_path = Path(db_path) if db_path else None
        self.container = container
        self.command, self.sleeper = command, sleeper

    def _run(self, args, input_text=None):
        result = self.command(args, input=input_text, text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError("n8n CLI command failed: " + " ".join(args[:5]))
        return result

    def import_workflow(self, workflow):
        # /dev/stdin keeps target-specific substitutions out of the working tree.
        self._run(["docker", "exec", "-i", self.container, "n8n", "import:workflow", "--input=/dev/stdin"],
                  json.dumps(workflow, ensure_ascii=False))

    def import_credentials(self, credentials):
        self._run(["docker", "exec", "-i", self.container, "n8n", "import:credentials", "--input=/dev/stdin"],
                  json.dumps(credentials))

    def publish(self, workflow_id):
        self._run(["docker", "exec", "-e", "N8N_SECURE_COOKIE=false", self.container, "n8n",
                   "publish:workflow", "--id=" + workflow_id])
        self._run(["docker", "restart", self.container])

    def unpublish(self, workflow_id):
        self._run(["docker", "exec", "-e", "N8N_SECURE_COOKIE=false", self.container, "n8n",
                   "unpublish:workflow", "--id=" + workflow_id])
        self._run(["docker", "restart", self.container])

    def version(self):
        """n8n version read from the container, not a constant (fixes T2 R-9)."""
        return self._run(["docker", "exec", self.container, "n8n", "--version"]).stdout.strip()

    def wait_ready(self, base_url, timeout=60):
        """Wait for the restarted local n8n HTTP service before the first submission."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urlopen(base_url.rstrip("/") + "/healthz", timeout=2) as response:
                    if response.status == 200:
                        # The health endpoint can respond before active webhooks register.
                        self.sleeper(5)
                        return
            except (OSError, URLError):
                pass
            self.sleeper(0.25)
        raise RuntimeError("n8n did not become ready after restart")

    def _container_query(self, sql, parameters):
        """Run a read-only SQLite query inside the local n8n container."""
        script = """const sqlite3=require('/usr/local/lib/node_modules/n8n/node_modules/sqlite3');
const input=JSON.parse(process.argv[1]);
const db=new sqlite3.Database('/home/node/.n8n/database.sqlite', sqlite3.OPEN_READONLY, error => {
  if (error) throw error;
  db.all(input.sql, input.parameters, (queryError, rows) => {
    if (queryError) throw queryError;
    process.stdout.write(JSON.stringify(rows));
    db.close();
  });
});"""
        result = self.command(["docker", "exec", self.container, "node", "-e", script,
                               json.dumps({"sql": sql, "parameters": list(parameters)})],
                              text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError("n8n SQLite query failed")
        return json.loads(result.stdout or "[]")

    def _query(self, sql, parameters):
        if self.db_path is not None:
            try:
                with sqlite3.connect("file:{}?mode=ro".format(self.db_path), uri=True) as connection:
                    return connection.execute(sql, parameters).fetchall()
            except sqlite3.OperationalError:
                pass
        return [tuple(row.values()) for row in self._container_query(sql, parameters)]

    def _decode_execution_data(self, value):
        """Decode n8n's bundled Flatted execution data without writing to SQLite."""
        script = """const flatted=require('/usr/local/lib/node_modules/n8n/node_modules/flatted');
const value=flatted.parse(process.argv[1]);
process.stdout.write(JSON.stringify(value));"""
        result = self.command(["docker", "exec", self.container, "node", "-e", script, value],
                              text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError("n8n execution-data decode failed")
        return json.loads(result.stdout)

    def latest_id(self, workflow_id):
        row = self._query("SELECT MAX(id) FROM execution_entity WHERE workflowId = ?", (workflow_id,))[0]
        return int(row[0] or 0)

    def credential_ids(self, names):
        placeholders = ",".join("?" for _ in names)
        rows = self._query("SELECT id, name FROM credentials_entity WHERE name IN ({})".format(placeholders),
                           tuple(names))
        ids = {row[1]: row[0] for row in rows}
        missing = sorted(set(names) - set(ids))
        if missing:
            raise RuntimeError("credentials missing in n8n (run setup): " + ", ".join(missing))
        return ids

    def wait_execution(self, workflow_id, after_id, timeout=TIMEOUT_SECONDS):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = self._query("SELECT id, status, startedAt, stoppedAt FROM execution_entity "
                               "WHERE workflowId = ? AND id > ? ORDER BY id DESC LIMIT 1",
                               (workflow_id, after_id))
            row = rows[0] if rows else None
            if row and row[1] not in ("new", "running", "waiting"):
                data_rows = self._query("SELECT data FROM execution_data WHERE executionId = ?", (row[0],))
                data = data_rows[0][0] if data_rows else None
                return {"id": int(row[0]), "status": row[1], "started": row[2], "stopped": row[3],
                        "data": (self._decode_execution_data(data) if data and data.lstrip().startswith("[")
                                 else json.loads(data) if data else None)}
            self.sleeper(0.25)
        return None


class LocalSink:
    """A fresh in-process sink and sandbox (src/sink/server.py) for one run, on its own thread."""

    def __init__(self, state_dir, env, host="0.0.0.0", port=8790):
        channels = (env.get("SLACK_CHANNEL_TRIAGE", ""), env.get("SLACK_CHANNEL_REVIEW", ""))
        self.server = make_server(state_dir, env["SINK_TOKEN"], env["JIRA_SANDBOX_EMAIL"],
                                  env["JIRA_SANDBOX_API_TOKEN"], env["SLACK_SANDBOX_BOT_TOKEN"], host, port,
                                  env.get("JIRA_PROJECT_KEY") or "SUP", channels)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.url = "http://127.0.0.1:{}".format(self.server.server_address[1])

    def start(self, token):
        self.thread.start()
        if request_json("GET", self.url + "/_health", token)[0] != 200:
            self.stop()
            raise RuntimeError("local sink did not become healthy")
        return self.url

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


# ---------------------------------------------------------------- execution data -> trace
def _first_json(entry):
    """First output item's json of one node run, or {}."""
    main = ((entry or {}).get("data") or {}).get("main")
    if isinstance(main, list):
        for branch in main:
            if isinstance(branch, list) and branch and isinstance(branch[0], dict):
                return branch[0].get("json") or {}
    return {}


def _usage(entry):
    usage = _first_json(entry).get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    return int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)


def _drop_headers(value):
    if isinstance(value, dict):
        return {k: _drop_headers(v) for k, v in value.items() if k.lower() != "headers"}
    if isinstance(value, list):
        return [_drop_headers(v) for v in value]
    return value


def llm_input(run_data, entry):
    """The H6 input item: `model_text` from the node that fed H6, else that item without headers."""
    source = (entry or {}).get("source") or []
    first = source[0] if source and isinstance(source[0], dict) else {}
    runs = run_data.get(first.get("previousNode") or "") or []
    index = first.get("previousNodeRun") or 0
    if not runs:
        return ""
    item = _first_json(runs[index] if index < len(runs) else runs[-1])
    if "model_text" in item:
        return str(item["model_text"])
    return json.dumps(_drop_headers(item), ensure_ascii=False, sort_keys=True)


def runner_event(run_id, pass_name, input_id, ok, **extra):
    event = {"ts": utc_now(), "node": "runner", "stage": "record", "ok": ok, "run_id": run_id, "pass": pass_name,
             "input_id": input_id, "tokens_in": 0, "tokens_out": 0, "usd": 0.0}
    event.update(extra)
    return event


def _iso(value):
    """n8n `startTime` is epoch milliseconds; trace timestamps are ISO UTC."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def trace_events(execution, run_id, pass_name, input_id, price_in, price_out):
    """One trace row per node run (Q-25); LLM rows add tokens, usd and `llm_input`."""
    if not execution:
        return [runner_event(run_id, pass_name, input_id, False, error="execution_timeout")]
    run_data = ((execution.get("data") or {}).get("resultData") or {}).get("runData") or {}
    events = []
    for node, entries in run_data.items():
        for entry in entries or []:
            event = {"ts": _iso(entry.get("startTime")) or execution.get("started") or utc_now(), "node": node,
                     "stage": stage_for(node), "ok": not entry.get("error"), "run_id": run_id, "pass": pass_name,
                     "input_id": input_id, "execution_id": execution["id"],
                     "duration_ms": entry.get("executionTime"), "tokens_in": 0, "tokens_out": 0, "usd": 0.0}
            if is_llm_node(node):
                tokens_in, tokens_out = _usage(entry)
                event.update(tokens_in=tokens_in, tokens_out=tokens_out,
                             usd=(tokens_in * price_in + tokens_out * price_out) / 1000000,
                             llm_input=llm_input(run_data, entry))
            if entry.get("error"):
                error = entry["error"]
                event["error"] = str(error.get("message") if isinstance(error, dict) else error)
            events.append(event)
    return events or [runner_event(run_id, pass_name, input_id, False, execution_id=execution["id"],
                                   error="no_execution_data")]


# ---------------------------------------------------------------- run
def _price(config, env, key):
    config_value, env_value = config.get(key), env.get(CONFIG_ENV[key])
    if config_value not in (None, "") and env_value not in (None, "") and float(config_value) != float(env_value):
        raise ValueError("{} in {} differs from {}".format(key, CONFIG_NODE, CONFIG_ENV[key]))
    value = config_value if config_value not in (None, "") else env_value
    if value in (None, ""):
        raise ValueError("{} not set in {} or {}".format(key, CONFIG_NODE, CONFIG_ENV[key]))
    return float(value)


def run_replay(args, n8n=None, env=None):
    """One replay run. Returns the run folder. Raises ValueError before any side effect when a check fails."""
    env = os.environ if env is None else env
    if args.target != "local":
        raise ValueError("only the local target exists in this build")
    require_env(env, RUN_ENV)
    run_cap, project_cap = float(env["RUN_USD_CAP"]), float(env["PROJECT_LLM_USD_CAP"])
    spent = project_spend(args.cost_ledger)
    if spent + run_cap > project_cap:
        raise ValueError("PROJECT_LLM_USD_CAP would be exceeded: ledger {:.4f} + RUN_USD_CAP {} > {}".format(
            spent, run_cap, project_cap))
    passes = args.passes or PHASES[args.phase][1]
    split = args.split or PHASES[args.phase][0]
    manifest_rows = load_manifest(args.manifest)
    ids = args.ids
    if args.phase == "attack" and not ids:
        ids = attacks.select_ids(manifest_rows, read_gold)
    rows = select_tickets(manifest_rows, args.phase, split, ids, args.limit)
    golds = {row["input_id"]: read_gold(row) for row in rows}
    forced = dict(parse_fault(spec) for spec in args.force_fault or ())
    unknown = sorted(set(forced) - set(golds))
    if unknown:
        raise ValueError("force-fault ids not in this run: " + ", ".join(unknown))

    source = Path(args.workflow)
    committed = json.loads(source.read_text(encoding="utf-8"))
    if not committed.get("id"):
        raise ValueError("workflow JSON has no id")
    static = check_file(str(source))
    if static["secrets"] or static["violations"]:
        raise ValueError("static checks fail on {} (run src.checks.static_checks --strict)".format(source.name))
    committed_config = config_values(committed)
    for key in ("run_usd_cap", "daily_usd_cap"):   # the committed caps must equal .env; overrides may differ
        if committed_config.get(key) not in (None, "") and env.get(CONFIG_ENV[key]) \
                and float(committed_config[key]) != float(env[CONFIG_ENV[key]]):
            raise ValueError("{} in committed {} differs from {}".format(key, CONFIG_NODE, CONFIG_ENV[key]))
    workflow = apply_overrides(committed, args.config_override)
    config = config_values(workflow)
    price_in, price_out = _price(config, env, "llm_price_in_per_mtok"), _price(config, env, "llm_price_out_per_mtok")
    handler_path = Path(args.handler_workflow) if args.handler_workflow else None
    handler = json.loads(handler_path.read_text(encoding="utf-8")) if handler_path and handler_path.exists() else None

    n8n = n8n or LocalN8n(args.sqlite, env.get("N8N_CONTAINER") or "n8n")
    cred_ids = n8n.credential_ids(tuple(CREDENTIAL_IDS))
    if handler is not None:
        handler = substitute(bind_credentials(handler, cred_ids), env)
    n8n_version = n8n.version()

    run_id = "{}-local-{}-{}".format(args.phase, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                                     git_short_sha())
    run_dir = Path(args.runs_dir) / run_id
    started = utc_now()
    segments = [{"name": "main", "dir": run_dir, "workflow": workflow, "tickets": [golds[r["input_id"]] for r in rows],
                 "passes": passes, "forced": forced, "overrides": list(args.config_override or ()),
                 "auth_probe": args.phase == "attack"}]
    if args.phase == "attack":      # isolated segments, each on its own sink (src/replay/attacks.py)
        all_golds = {row["input_id"]: read_gold(row) for row in manifest_rows}
        for seg in attacks.plan_segments(all_golds, committed_config.get("max_model_chars"), started):
            segments.append(dict(seg, dir=run_dir / "segments" / seg["name"], forced={},
                                 workflow=apply_overrides(committed, seg["overrides"])))
    run_dir.mkdir(parents=True)
    (run_dir / "static_checks.json").write_text(json.dumps(static, indent=2, sort_keys=True) + "\n",
                                                encoding="utf-8")
    ctx = {"n8n": n8n, "env": env, "args": args, "run_id": run_id, "handler": handler, "cred_ids": cred_ids,
           "price": (price_in, price_out), "run_cap": run_cap, "scrub": scrubber(env), "spent": 0.0,
           "webhook": env["N8N_BASE_URL"].rstrip("/") + "/webhook/" + env["T4_WEBHOOK_PATH"]}
    aborted, done = None, []
    for seg in segments:
        result = _replay_segment(seg, ctx)
        ctx["spent"] += result["usd"]
        done.append((seg, result))
        if result["aborted"]:
            aborted = result["aborted"]
            break
    ended = utc_now()

    scrub = ctx["scrub"]
    totals = {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0, "capped": 0, "tickets": 0}
    seg_summaries = []
    for seg, result in done:
        events = result["events"]
        llm = [e for e in events if is_llm_node(e["node"])]
        facts = {"llm_calls": len(llm), "tokens_in": sum(e["tokens_in"] for e in llm),
                 "tokens_out": sum(e["tokens_out"] for e in llm), "usd": result["usd"], "capped": result["capped"],
                 "tickets": len(seg["tickets"])}
        for key in totals:
            totals[key] += facts[key]
        seg["dir"].mkdir(parents=True, exist_ok=True)
        with (seg["dir"] / "trace.jsonl").open("w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
        if result["probe"] is not None:
            (run_dir / "auth_probe.json").write_text(json.dumps(scrub(result["probe"]), indent=2) + "\n",
                                                     encoding="utf-8")
        later = set(seg["passes"][1:])
        issues = read_csv(seg["dir"] / "sink" / "jira_issues.csv")
        seg_config = config_values(seg["workflow"])
        is_main = seg is segments[0]
        summary = {
            "run_id": run_id, "phase": args.phase, "split": split, "target": "local", "passes": seg["passes"],
            "input_ids": [g["input_id"] for g in seg["tickets"]], "tickets": len(seg["tickets"]),
            "started": started, "ended": ended, "git_sha": run_id.rsplit("-", 1)[1],
            "model": seg_config.get("llm_model"), "n8n_version": n8n_version,
            "workflow_sha256": sha256_file(source), "handler_sha256": sha256_file(handler_path) if handler else None,
            "thresholds_sha256": sha256_file(THRESHOLDS), "prompt_sha256": prompt_sha256(committed),
            "config_overrides": seg["overrides"], "forced_faults": list(args.force_fault or ()) if is_main else [],
            "run_usd_cap": run_cap, "max_model_chars": seg_config.get("max_model_chars"),
            "llm_price_in_per_mtok": price_in, "llm_price_out_per_mtok": price_out,
            "llm_calls": facts["llm_calls"], "tokens_in": facts["tokens_in"], "tokens_out": facts["tokens_out"],
            "usd": facts["usd"], "capped_inputs": facts["capped"],
            "new_jira_issues_pass_b": sum(1 for r in issues if r.get("replay_pass") in later),
            "llm_calls_pass_b": sum(1 for e in llm if e["pass"] in later),
            "aborted": scrub(str(result["aborted"])) if result["aborted"] else None,
        }
        if is_main:
            main_summary = summary
        else:
            summary.update(segment=seg["name"], run_id_mode=seg.get("run_id_mode"), config={
                k: seg_config.get(k) for k in ("run_usd_cap", "daily_usd_cap", "llm_max_rpm", "tuning_mode")})
            seg_summaries.append({"name": seg["name"], "dir": "segments/" + seg["name"], "passes": seg["passes"],
                                  "tickets": facts["tickets"], "config_overrides": seg["overrides"],
                                  "run_id_mode": seg.get("run_id_mode"), "llm_calls": facts["llm_calls"],
                                  "usd": facts["usd"], "capped_inputs": facts["capped"],
                                  "roles": seg.get("roles")})
        (seg["dir"] / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if len(segments) > 1:            # the main summary also carries the whole-run totals (= the ledger row)
        main_summary.update(segments=seg_summaries, run_totals=dict(totals))
        (run_dir / "summary.json").write_text(json.dumps(main_summary, indent=2) + "\n", encoding="utf-8")
    ledger = Path(args.cost_ledger)
    write_header = not ledger.exists()
    with ledger.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_HEADER, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerow({"run_id": run_id, "run_phase": args.phase, "target": "local", "started_utc": started,
                         "ended_utc": ended, "model": config.get("llm_model") or "",
                         "llm_calls": totals["llm_calls"], "tokens_in": totals["tokens_in"],
                         "tokens_out": totals["tokens_out"], "usd": totals["usd"], "run_usd_cap": run_cap,
                         "capped_inputs": totals["capped"], "tickets": totals["tickets"],
                         "usd_per_1k_tickets": totals["usd"] / totals["tickets"] * 1000})
    if aborted:
        raise aborted
    if args.phase == "attack":       # after every run file exists, so the scan covers them (SEC-20)
        values = {name: env.get(name) or "" for name in SECRET_ENV}
        scan = attacks.secret_scan(ROOT, values)
        (run_dir / "secret_scan.json").write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
        attacks.write_results(run_dir, {row["input_id"]: read_gold(row) for row in manifest_rows})
    return run_dir


def _replay_segment(seg, ctx):
    """One workflow import over a fresh sink in `seg['dir']/sink`: publish, submit the tickets one at a time (I-7),
    unpublish. Returns events, capped count, usd, the exception that stopped it (or None) and the SEC-18 probe."""
    n8n, env, args, run_id, scrub = ctx["n8n"], ctx["env"], ctx["args"], ctx["run_id"], ctx["scrub"]
    workflow, handler = substitute(bind_credentials(seg["workflow"], ctx["cred_ids"]), env), ctx["handler"]
    sink_dir, token = Path(seg["dir"]) / "sink", env["SINK_TOKEN"]
    events, capped, trace_usd, probe = [], 0, 0.0, None
    sink = LocalSink(sink_dir, env, args.sink_host, args.sink_port)
    sink_url = sink.start(token)
    published, aborted = [], None
    try:
        if handler is not None:
            n8n.import_workflow(handler)
            published.append(handler["id"])
            n8n.publish(handler["id"])  # n8n runs an error workflow only when it is published.
        n8n.import_workflow(workflow)
        published.append(workflow["id"])
        n8n.publish(workflow["id"])
        n8n.wait_ready(env["N8N_BASE_URL"])
        for pass_name in seg["passes"]:
            for index, gold in enumerate(seg["tickets"]):
                input_id = gold["input_id"]
                if ctx["spent"] + max(trace_usd, ledger_usd(sink_dir, run_id)) >= ctx["run_cap"]:
                    capped += 1
                    events.append(runner_event(run_id, pass_name, input_id, False, capped=True,
                                               error="runner_cap"))
                    continue
                status, _ = request_json("POST", sink_url + "/_replay/active", token,
                                         {"input_id": input_id, "pass": pass_name})
                if status != 200:
                    raise RuntimeError("sink did not accept the active input")
                fault = seg["forced"].get(input_id) or gold.get("fault") or {}
                fault_name = ""
                if fault and fault.get("pass", "A") == pass_name:
                    body = {k: fault[k] for k in ("target", "mode", "pass") if k in fault}
                    if request_json("POST", sink_url + "/_replay/fault", token, body)[0] != 200:
                        raise RuntimeError("sink did not accept the fault for " + input_id)
                    fault_name = "{}:{}".format(fault["target"], fault["mode"])
                # SEC-13 sends a fresh X-Replay-Run-Id per request (T2 R-2); every other run sends the run id.
                header_run_id = "{}-r{:02d}".format(run_id, index + 1) \
                    if seg.get("run_id_mode") == "per_request" else run_id
                before = n8n.latest_id(workflow["id"])
                http_status = submit(ctx["webhook"], env["T4_WEBHOOK_TOKEN"], header_run_id, gold, args.timeout)
                events.append(runner_event(run_id, pass_name, input_id, 200 <= http_status < 300, stage="intake",
                                           http_status=http_status, fault=fault_name))
                if http_status in (401, 403, 404):
                    raise RuntimeError("webhook returned HTTP {} (token or path wrong?)".format(http_status))
                execution = n8n.wait_execution(workflow["id"], before, args.timeout)
                ticket_events = [scrub(e) for e in trace_events(execution, run_id, pass_name, input_id,
                                                                *ctx["price"])]
                for event in ticket_events:
                    if "llm_input" in event:
                        request_json("POST", sink_url + "/_replay/llm_input", token, {"llm_input": event["llm_input"]})
                events.extend(ticket_events)
                trace_usd += sum(float(e.get("usd") or 0) for e in ticket_events)
                request_json("POST", sink_url + "/_replay/fault", token, {"clear": True})
        if seg.get("auth_probe") and seg["tickets"]:
            request_json("POST", sink_url + "/_replay/active", token, {"input_id": "sec18-probe", "pass": "A"})
            probe = attacks.auth_probe(ctx["webhook"], seg["tickets"][0], lambda: n8n.latest_id(workflow["id"]),
                                       lambda: len(read_csv(sink_dir / "ledger.csv")))
    except Exception as error:      # keep the evidence (and the spend) of a run that stopped half way, then re-raise
        aborted = error
    finally:
        try:
            for workflow_id in reversed(published):
                n8n.unpublish(workflow_id)
        finally:
            sink.stop()
    return {"events": events, "capped": capped, "usd": max(trace_usd, ledger_usd(sink_dir, run_id)),
            "aborted": aborted, "probe": probe}


def setup(env=None, n8n=None):
    """Import the five credentials from memory. Nothing is printed or written."""
    env = os.environ if env is None else env
    require_env(env, SETUP_ENV)
    n8n = n8n or LocalN8n(None, env.get("N8N_CONTAINER") or "n8n")
    n8n.import_credentials(credential_payload(env))
    return sorted(CREDENTIAL_IDS)


# Owner-run demo against a real Jira Cloud site and Slack workspace (close plan D-1, ADR-003 note in ARCHITECTURE §7).
# Real values live under *_REAL_* names so the sandbox names never point at a real host by accident.
REAL_ENV = {"JIRA_BASE_URL": "JIRA_REAL_BASE_URL", "JIRA_SANDBOX_EMAIL": "JIRA_REAL_EMAIL",
            "JIRA_SANDBOX_API_TOKEN": "JIRA_REAL_API_TOKEN", "SLACK_SANDBOX_BOT_TOKEN": "SLACK_REAL_BOT_TOKEN"}
REAL_CONFIG = {"jira_project_key": "JIRA_REAL_PROJECT_KEY", "slack_channel_triage": "SLACK_REAL_CHANNEL_TRIAGE",
               "slack_channel_review": "SLACK_REAL_CHANNEL_REVIEW"}
REAL_MAX_TICKETS = 3


def real_env(env):
    """A copy of env with the real values under the names the workflow and credentials use."""
    require_env(env, list(REAL_ENV.values()) + list(REAL_CONFIG.values()))
    out = dict(env)
    for name, real in REAL_ENV.items():
        out[name] = env[real]
    out["SLACK_BASE_URL"] = "https://slack.com"
    return out


def real_overrides(env):
    return ["{}={}".format(key, env[name]) for key, name in REAL_CONFIG.items()]


def run_real(args, n8n=None, env=None):
    """Smoke run on at most REAL_MAX_TICKETS ids with real credentials; sandbox credentials are restored after."""
    env = os.environ if env is None else env
    if args.phase != "smoke" or not args.ids or len(args.ids) > REAL_MAX_TICKETS:
        raise ValueError("--real needs --phase smoke and 1..{} --ids".format(REAL_MAX_TICKETS))
    real = real_env(env)
    args.config_override = list(args.config_override or ()) + real_overrides(env)
    n8n = n8n or LocalN8n(args.sqlite, env.get("N8N_CONTAINER") or "n8n")
    n8n.import_credentials(credential_payload(real))
    try:
        return run_replay(args, n8n=n8n, env=real)
    finally:
        n8n.import_credentials(credential_payload(env))


def build_parser():
    parser = argparse.ArgumentParser(prog="python3 -m src.replay.run", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("setup", "run"))
    parser.add_argument("--target", default="local", choices=("local",))
    parser.add_argument("--phase", choices=sorted(PHASES), help="required for run")
    parser.add_argument("--split", choices=("dev", "test"), help="default: by phase (attack: both)")
    parser.add_argument("--ids", nargs="+", help="input ids (space or comma separated), manifest order kept")
    parser.add_argument("--limit", type=int, help="first N selected tickets")
    parser.add_argument("--passes", choices=("A", "AB"), help="default: by phase (smoke, test: AB)")
    parser.add_argument("--force-fault", action="append", metavar="ID:TARGET:MODE[:PASS]",
                        help="sink fault for one ticket, e.g. t4-007:sink:jira_links:503 (default pass A)")
    parser.add_argument("--config-override", action="append", metavar="KEY=VALUE",
                        help="in-memory change to a 0. Config value for this run (recorded in summary.json)")
    parser.add_argument("--workflow", default=str(WORKFLOW))
    parser.add_argument("--handler-workflow", default=str(HANDLER))
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--sqlite", default=None, help="host path to n8n SQLite (default: query in the container)")
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--runs-dir", default=str(RUNS_DIR))
    parser.add_argument("--cost-ledger", default=str(COST_LEDGER))
    parser.add_argument("--sink-host", default="0.0.0.0", help="the n8n container reaches the sink on the host")
    parser.add_argument("--sink-port", type=int, default=None, help="default: SINK_PORT or 8790")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS, help="seconds per ticket")
    parser.add_argument("--real", action="store_true",
                        help="owner-run demo: real Jira/Slack from *_REAL_* names; smoke phase, <= 3 ids")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    load_env_file(args.env_file)
    try:
        if args.command == "setup":
            names = setup()
            print("setup: imported credentials " + ", ".join(names))
            return 0
        if not args.phase:
            raise ValueError("run needs --phase")
        if args.sink_port is None:
            args.sink_port = int(os.environ.get("SINK_PORT") or "8790")
        run_dir = run_real(args) if args.real else run_replay(args)
    except (ValueError, RuntimeError) as error:
        print("replay refused: {}".format(error), file=sys.stderr)
        return 2
    print("run folder: {}".format(run_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
