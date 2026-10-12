"""Append-only evidence sink plus Jira and Slack contract sandboxes on one port (ADR-003, ARCHITECTURE §6.3, §7).

Route groups, by path prefix, each with its own credential:
  sink   /append/<table> /lookup/<table> /ledger/sum /ledger/count /_replay/* /_health    X-Sink-Token
  jira   /rest/...   only GET /rest/api/3/search/jql and POST /rest/api/3/issue          HTTP Basic
  slack  /api/...    only POST /api/chat.postMessage                                      Bearer
A wrong or missing credential is 403 in every group. Any other method or path under /rest/ or /api/ is 403.
No route updates or deletes a row (I-5). Every request is one row in requests.jsonl; headers are never written.

    SINK_TOKEN=… JIRA_SANDBOX_EMAIL=… JIRA_SANDBOX_API_TOKEN=… SLACK_SANDBOX_BOT_TOKEN=… \\
        python3 -m src.sink.server --state-dir evals/runs/<run_id>/sink
"""
from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hmac
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


STAMPS = ("sink_seq", "sink_ts", "replay_input_id", "replay_pass")
SINK_COLUMNS = {
    "audit": ("run_id", "input_ref", "execution_id", "stage", "node", "ok", "status", "dedupe_key", "content_sha256",
              "category", "conf_category", "priority", "conf_priority", "urgency", "conf_source", "reasons",
              "pii_counts", "injection_signals", "truncated", "issue_key", "notify_ok", "capped", "tokens_in",
              "tokens_out", "usd", "duration_ms"),
    "ledger": ("run_id", "input_ref", "day", "model", "tokens_in", "tokens_out", "usd"),
    "review_queue": ("run_id", "dedupe_key", "reasons", "category", "conf_category", "priority", "conf_priority",
                     "urgency", "redacted_subject", "redacted_body"),
    "jira_links": ("run_id", "dedupe_key", "issue_key", "category", "priority", "created_via"),
    "errors": ("run_id", "input_ref", "stage", "node", "code", "message"),
}
SANDBOX_COLUMNS = {
    "jira_issues": ("key", "project", "issuetype", "summary", "description_text", "labels", "priority",
                    "created_seq"),
    "slack_messages": ("channel", "text", "unfurl_links"),
}
COLUMNS = dict(SINK_COLUMNS, **SANDBOX_COLUMNS)
# (target, mode) pairs the runner may set per ticket (GOALS G5, HARNESS_SPEC §1.3 `fault`).
FAULTS = {("jira", "503"), ("jira", "commit_then_504"), ("jira", "search_lag"), ("slack", "503"),
          ("sink:jira_links", "503")}
DEFAULT_LAG_REQUESTS = 100     # search_lag hides issues created fewer than this many requests ago (OPEN_QUESTIONS Q-29)
MAX_BODY = 2_000_000
JIRA_ISSUE_TYPE = "Task"
JIRA_PRIORITIES = ("Highest", "High", "Medium", "Low")
JIRA_FIELDS = ("project", "issuetype", "summary", "description", "labels", "priority")
JIRA_SEARCH = "/rest/api/3/search/jql"
JIRA_CREATE = "/rest/api/3/issue"
SLACK_POST = "/api/chat.postMessage"
JQL = re.compile(r'^\s*(?:project\s*=\s*"?([A-Za-z0-9_]+)"?\s+and\s+)?labels\s*=\s*"([^"\s]+)"\s*$', re.IGNORECASE)
ENV_SECRETS = ("SINK_TOKEN", "JIRA_SANDBOX_EMAIL", "JIRA_SANDBOX_API_TOKEN", "SLACK_SANDBOX_BOT_TOKEN")


def _now():
    return datetime.now(timezone.utc)


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def _json_object(raw):
    if not raw:
        raise ValueError("body must be a JSON object")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("body must be a JSON object")
    return value


def _single(query):
    """Query string -> {name: value}; a repeated name is an error."""
    parsed = parse_qs(query, keep_blank_values=True)
    if any(len(values) != 1 for values in parsed.values()):
        raise ValueError("query parameters must be single-valued")
    return {name: values[0] for name, values in parsed.items()}


def _adf_text(node):
    """Plain text of an Atlassian Document Format node; top-level blocks are joined by newlines."""
    if isinstance(node, list):
        return "".join(_adf_text(child) for child in node)
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    if node.get("type") == "hardBreak":
        return "\n"
    parts = [_adf_text(child) for child in node.get("content") or []]
    return ("\n" if node.get("type") == "doc" else "").join(parts)


def _same(supplied, expected):
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def route_group(path):
    if path.startswith("/rest/"):
        return "jira"
    if path.startswith("/api/"):
        return "slack"
    return "sink"


class SinkState:
    """Tables on disk under `directory`; replay state (active input, fault) in memory."""

    def __init__(self, directory, sink_token, jira_email, jira_token, slack_token, project_key="SUP", channels=()):
        missing = [name for name, value in (("sink_token", sink_token), ("jira_email", jira_email),
                                            ("jira_token", jira_token), ("slack_token", slack_token)) if not value]
        if missing:
            raise ValueError("missing secret(s): " + ", ".join(missing))
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.sink_token = sink_token
        self.jira_basic = "{}:{}".format(jira_email, jira_token)
        self.slack_token = slack_token
        self.project_key = project_key
        self.channels = frozenset(c for c in channels if c)
        self.active_input = ""
        self.active_pass = ""
        self.fault = None
        self.issue_born = {}           # issue key -> request number of its create (search_lag)
        self.seq = 0
        for table in COLUMNS:
            for row in self.rows(table):
                self.seq = max(self.seq, int(row.get("sink_seq") or 0))
        self.issue_seq = max([int(r.get("created_seq") or 0) for r in self.rows("jira_issues")] + [0])
        self.request_seq = 0           # request number; `_dispatch` counts every request, `seq` in requests.jsonl
        log = self.directory / "requests.jsonl"
        if log.exists():
            with log.open(encoding="utf-8") as f:
                self.request_seq = sum(1 for line in f if line.strip())

    # ------------------------------------------------------------ tables
    def rows(self, table):
        path = self.directory / (table + ".csv")
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def write_row(self, table, values):
        header = STAMPS + COLUMNS[table]
        self.seq += 1
        row = {key: "" for key in header}
        row.update({key: _csv_value(value) for key, value in values.items()})
        row.update({"sink_seq": str(self.seq), "sink_ts": _now().isoformat(),
                    "replay_input_id": self.active_input, "replay_pass": self.active_pass})
        path = self.directory / (table + ".csv")
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
            if f.tell() == 0:
                writer.writeheader()
            writer.writerow(row)
        return row

    def log(self, event):
        with (self.directory / "requests.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")

    # ------------------------------------------------------------ faults
    def take_fault(self, target, mode):
        """True if the active fault matches and fires now; `times` counts firings down to zero."""
        fault = self.fault
        if not fault or fault["target"] != target or fault["mode"] != mode:
            return False
        if fault["pass"] and fault["pass"] != self.active_pass:
            return False
        if fault["times"] is not None:
            fault["times"] -= 1
            if fault["times"] <= 0:
                self.fault = None
        return True

    def set_fault(self, body):
        if body.get("clear") is True and len(body) == 1:
            self.fault = None
            return 200, {"ok": True, "fault": None}
        target, mode = body.get("target"), str(body.get("mode"))
        times, run_pass, lag = body.get("times"), body.get("pass"), body.get("lag_requests")
        if not isinstance(target, str) or (target, mode) not in FAULTS:
            raise ValueError("unknown fault; allowed: " + ", ".join(sorted(t + ":" + m for t, m in FAULTS)))
        if set(body) - {"target", "mode", "times", "pass", "lag_requests"}:
            raise ValueError("unknown fault field")
        if run_pass not in (None, "A", "B"):
            raise ValueError("fault pass must be A or B")
        for name, value in (("times", times), ("lag_requests", lag)):
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(name + " must be a positive integer")
        if lag is not None and mode != "search_lag":
            raise ValueError("lag_requests applies to search_lag only")
        self.fault = {"target": target, "mode": mode, "times": times, "pass": run_pass,
                      "lag_requests": lag or DEFAULT_LAG_REQUESTS}
        return 200, {"ok": True, "fault": target + ":" + mode}

    # ------------------------------------------------------------ dispatch
    def handle(self, method, path, query, raw, headers, host):
        """One request -> (status, reply, note). `note` adds `target`, `fault` to the request-log row."""
        note = {"target": route_group(path)}
        group = note["target"]
        if group == "jira":
            if not self._basic_ok(headers.get("Authorization", "")):
                return 403, {"errorMessages": ["forbidden"]}, note
            if method == "GET" and path == JIRA_SEARCH:
                return self._jira_search(query, note) + (note,)
            if method == "POST" and path == JIRA_CREATE:
                return self._jira_create(raw, host, note) + (note,)
            return 403, {"errorMessages": ["method or path not allowed in the sandbox"]}, note
        if group == "slack":
            if not self._bearer_ok(headers.get("Authorization", "")):
                return 403, {"ok": False, "error": "invalid_auth"}, note
            if method == "POST" and path == SLACK_POST:
                return self._slack_post(raw, note) + (note,)
            return 403, {"ok": False, "error": "method_not_allowed"}, note
        if not _same(headers.get("X-Sink-Token", ""), self.sink_token):
            return 403, {"error": "forbidden"}, note
        return self._sink(method, path, query, raw, note) + (note,)

    def _basic_ok(self, header):
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            supplied = base64.b64decode(value.strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        return _same(supplied, self.jira_basic)

    def _bearer_ok(self, header):
        scheme, _, value = header.partition(" ")
        return scheme.lower() == "bearer" and _same(value.strip(), self.slack_token)

    # ------------------------------------------------------------ sink routes
    def _sink(self, method, path, query, raw, note):
        if method == "GET" and path == "/_health":
            return 200, {"ok": True}
        if method == "POST" and path == "/_replay/active":
            body = _json_object(raw)
            if not isinstance(body.get("input_id"), str) or not body["input_id"] or body.get("pass") not in ("A", "B"):
                raise ValueError("active requires input_id and pass A or B")
            self.active_input, self.active_pass = body["input_id"], body["pass"]
            self.fault = None
            return 200, {"ok": True}
        if method == "POST" and path == "/_replay/fault":
            return self.set_fault(_json_object(raw))
        if method == "POST" and path == "/_replay/llm_input":
            body = _json_object(raw)
            if not isinstance(body.get("llm_input"), str):
                raise ValueError("llm_input must be a string")
            note["target"] = "llm"
            return 200, {"ok": True}
        if method == "POST" and path.startswith("/append/"):
            table = path[len("/append/"):]
            if table not in SINK_COLUMNS:
                raise ValueError("unknown table")
            body = _json_object(raw)
            if not body or set(body) & set(STAMPS):
                raise ValueError("append body must be a nonempty object without sink stamps")
            if set(body) - set(SINK_COLUMNS[table]):
                raise ValueError("unknown column(s): " + ", ".join(sorted(set(body) - set(SINK_COLUMNS[table]))))
            if self.take_fault("sink:" + table, "503"):
                note["fault"] = "sink:" + table + ":503"
                return 503, {"error": "injected fault"}
            return 200, {"row": self.write_row(table, body)}
        if method == "GET" and path.startswith("/lookup/"):
            table = path[len("/lookup/"):]
            if table not in SINK_COLUMNS:
                raise ValueError("unknown table")
            filters = _single(query)
            if not filters:
                raise ValueError("lookup requires at least one filter")
            if set(filters) - set(STAMPS + SINK_COLUMNS[table]):
                raise ValueError("unknown filter column")
            # `a|b` matches either value (ARCHITECTURE C-18: status=auto_routed|review).
            rows = [row for row in self.rows(table)
                    if all(row.get(col, "") in value.split("|") for col, value in filters.items())]
            return 200, {"count": len(rows), "rows": rows}
        if method == "GET" and path == "/ledger/sum":
            filters = _single(query)
            if len(filters) != 1 or next(iter(filters)) not in ("day", "run_id") or not next(iter(filters.values())):
                raise ValueError("ledger/sum requires exactly one of day= or run_id=")
            (col, value), = filters.items()
            rows = [row for row in self.rows("ledger") if row.get(col) == value]
            try:
                amount = sum((Decimal(row.get("usd") or "0") for row in rows), Decimal("0"))
            except InvalidOperation as error:
                raise ValueError("invalid ledger usd") from error
            return 200, {"usd": float(amount), "count": len(rows)}
        if method == "GET" and path == "/ledger/count":
            filters = _single(query)
            if set(filters) != {"since_s"}:
                raise ValueError("ledger/count requires since_s= only")
            since = float(filters["since_s"])
            if not math.isfinite(since) or since < 0:
                raise ValueError("since_s must be a nonnegative number")
            threshold = _now() - timedelta(seconds=since)
            count = sum(datetime.fromisoformat(row["sink_ts"]) >= threshold for row in self.rows("ledger"))
            return 200, {"count": count}
        return 404, {"error": "not found"}

    # ------------------------------------------------------------ jira routes
    def _jira_search(self, query, note):
        params = _single(query)
        match = JQL.match(params.get("jql", ""))
        if not match:
            return 400, {"errorMessages": ['sandbox JQL is labels = "<label>", optionally after project = <key> AND']}
        project, label = match.groups()
        if project is not None and project != self.project_key:
            return 403, {"errorMessages": ["project not allowed"]}
        try:
            limit = int(params.get("maxResults", "50"))
        except ValueError:
            limit = 0
        if not 1 <= limit <= 100:
            return 400, {"errorMessages": ["maxResults must be 1..100"]}
        issues = [row for row in self.rows("jira_issues") if label in row["labels"].split("|")]
        lag = (self.fault or {}).get("lag_requests", DEFAULT_LAG_REQUESTS)
        if self.take_fault("jira", "search_lag"):
            note.update({"fault": "jira:search_lag", "lag_requests": lag})
            # Issues read from disk at start have no request number: they count as old and stay visible.
            issues = [row for row in issues if row["key"] not in self.issue_born
                      or self.request_seq - self.issue_born[row["key"]] >= lag]
        found = [{"id": str(10000 + int(row["created_seq"])), "key": row["key"]} for row in issues[:limit]]
        return 200, {"issues": found, "isLast": len(issues) <= limit}

    def _jira_create(self, raw, host, note):
        body = _json_object(raw)
        fields = body.get("fields")
        if not isinstance(fields, dict) or set(body) != {"fields"}:
            return 400, {"errorMessages": ["body must be {\"fields\": {...}}"]}
        project = fields.get("project") if isinstance(fields.get("project"), dict) else {}
        issuetype = fields.get("issuetype") if isinstance(fields.get("issuetype"), dict) else {}
        if project.get("key") != self.project_key or set(project) != {"key"}:
            return 403, {"errorMessages": ["project not allowed"]}
        if issuetype.get("name") != JIRA_ISSUE_TYPE or set(issuetype) != {"name"}:
            return 403, {"errorMessages": ["issue type not allowed"]}
        errors = {name: "Field '{}' cannot be set. It is not on the appropriate screen, or unknown.".format(name)
                  for name in sorted(set(fields) - set(JIRA_FIELDS))}
        summary = fields.get("summary")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 255 or "\n" in summary:
            errors["summary"] = "summary must be one line of 1..255 characters"
        labels = fields.get("labels", [])
        if not isinstance(labels, list) or not all(isinstance(x, str) and x and not re.search(r"\s", x)
                                                   for x in labels):
            errors["labels"] = "labels must be a list of strings without spaces"
        priority = fields.get("priority")
        if priority is not None and (not isinstance(priority, dict) or set(priority) != {"name"}
                                     or priority["name"] not in JIRA_PRIORITIES):
            errors["priority"] = "priority must be {\"name\": Highest|High|Medium|Low}"
        description = fields.get("description")
        if description is not None and (not isinstance(description, dict) or description.get("type") != "doc"):
            errors["description"] = "description must be an ADF document"
        if errors:
            return 400, {"errorMessages": [], "errors": errors}
        if self.take_fault("jira", "503"):
            note["fault"] = "jira:503"
            return 503, {"errorMessages": ["injected fault: service unavailable"]}
        self.issue_seq += 1
        key = "{}-{}".format(self.project_key, self.issue_seq)
        self.write_row("jira_issues", {
            "key": key, "project": self.project_key, "issuetype": JIRA_ISSUE_TYPE, "summary": summary,
            "description_text": _adf_text(description), "labels": "|".join(labels),
            "priority": (priority or {}).get("name", ""), "created_seq": self.issue_seq})
        self.issue_born[key] = self.request_seq
        if self.take_fault("jira", "commit_then_504"):
            note["fault"] = "jira:commit_then_504"
            return 504, {"errorMessages": ["injected fault: gateway timeout after commit"]}
        issue_id = str(10000 + self.issue_seq)
        return 201, {"id": issue_id, "key": key, "self": "http://{}{}/{}".format(host, JIRA_CREATE, issue_id)}

    # ------------------------------------------------------------ slack routes
    def _slack_post(self, raw, note):
        body = _json_object(raw)
        channel, text = body.get("channel"), body.get("text")
        if not isinstance(channel, str) or not channel or not isinstance(text, str) or not text:
            return 400, {"ok": False, "error": "invalid_arguments"}
        if self.channels and channel not in self.channels:
            return 403, {"ok": False, "error": "not_in_channel"}
        if self.take_fault("slack", "503"):
            note["fault"] = "slack:503"
            return 503, {"ok": False, "error": "injected_fault"}
        row = self.write_row("slack_messages", {"channel": channel, "text": text,
                                                "unfurl_links": body.get("unfurl_links")})
        return 200, {"ok": True, "channel": channel, "ts": "{}.{:06d}".format(int(time.time()), int(row["sink_seq"]))}


def make_server(state_dir, sink_token, jira_email, jira_token, slack_token, host="127.0.0.1", port=0,
                project_key="SUP", channels=()):
    """Return a single-threaded server (I-7: replay is sequential). Port zero selects an ephemeral test port."""
    state = SinkState(state_dir, sink_token, jira_email, jira_token, slack_token, project_key, channels)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format_string, *args):
            pass

        def _reply(self, status, body):
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _raw(self):
            size = int(self.headers.get("Content-Length") or "0")
            if size < 0 or size > MAX_BODY:
                raise ValueError("invalid body size")
            return self.rfile.read(size) if size else b""

        def _dispatch(self):
            url = urlsplit(self.path)
            state.request_seq += 1
            raw = b""
            note = {"target": route_group(url.path)}
            try:
                raw = self._raw()
                status, reply, note = state.handle(self.command, url.path, url.query, raw, self.headers,
                                                   self.headers.get("Host", ""))
            except (ValueError, UnicodeDecodeError) as error:      # json.JSONDecodeError is a ValueError
                status, reply = 400, {"error": str(error)}
            except Exception:                                      # keep the log row even on a sink bug
                status, reply = 500, {"error": "internal error"}
            event = {"seq": state.request_seq, "ts": _now().isoformat(), "method": self.command, "path": url.path,
                     "status": status, "active_input": state.active_input, "pass": state.active_pass}
            event.update(note)
            if note["target"] in ("jira", "slack", "llm") and raw:
                try:
                    event["body"] = json.loads(raw)
                except ValueError:
                    event["body"] = raw.decode("utf-8", errors="replace")
            state.log(event)
            self._reply(status, reply)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _dispatch

    server = HTTPServer((host, port), Handler)
    server.state = state
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SINK_PORT") or "8790"))
    args = parser.parse_args(argv)
    missing = [name for name in ENV_SECRETS if not os.environ.get(name)]
    if missing:
        print("sink refuses to start; not set: " + ", ".join(missing), file=sys.stderr)
        return 2
    env = os.environ
    channels = (env.get("SLACK_CHANNEL_TRIAGE", ""), env.get("SLACK_CHANNEL_REVIEW", ""))
    with make_server(args.state_dir, env["SINK_TOKEN"], env["JIRA_SANDBOX_EMAIL"], env["JIRA_SANDBOX_API_TOKEN"],
                     env["SLACK_SANDBOX_BOT_TOKEN"], args.host, args.port, env.get("JIRA_PROJECT_KEY") or "SUP",
                     channels) as server:
        print("sink listening on {}:{} state {}".format(args.host, server.server_address[1], args.state_dir))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
