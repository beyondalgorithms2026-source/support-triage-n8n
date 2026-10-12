"""Secret scan and configuration audit for exported n8n workflow JSON.

Ported from T2 `src/checks/static_checks.py`. T4 adds: allowed-host placeholders on every HTTP Request URL,
no `$env` anywhere, Jira create without retryOnFail, and a report of every Jira and Slack path used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys


SECRET_PATTERNS = (
    r"sk-[A-Za-z0-9_-]{20,}",
    r"sk-proj-",
    r"ya29\.",
    r"AIza[0-9A-Za-z_-]{35}",
    r"Bearer [A-Za-z0-9._-]{20,}",
    r'"(access|refresh)_token"\s*:\s*"[^"]+"',
    r'"apiKey"\s*:\s*"[^"={]+"',
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"xox[abpr]-[A-Za-z0-9-]{10,}",
)
_COMPILED_PATTERNS = tuple((pattern, re.compile(pattern)) for pattern in SECRET_PATTERNS)
EXTERNAL_TYPES = {"httpRequest", "googleSheets", "gmail", "openAi", "jira", "slack"}
ALLOWED_HOSTS = ("__SINK_BASE_URL__", "__JIRA_BASE_URL__", "__SLACK_BASE_URL__", "https://api.openai.com")
PATH_TARGETS = {"__JIRA_BASE_URL__": "jira", "__SLACK_BASE_URL__": "slack"}
JIRA_CREATE_PATH = re.compile(r"^/rest/api/[23]/issue/?$")


def scan_secrets(text):
    """Return one location record per matching pattern occurrence, without values."""
    findings = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for pattern, compiled in _COMPILED_PATTERNS:
            if compiled.search(line):
                findings.append({"pattern": pattern, "line": line_number})
    return findings


def _positive_timeout(value):
    if isinstance(value, bool):
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def split_url(url, allowed_hosts):
    """Return (host, path) when url starts with an allowed host at a boundary, else (None, None).

    A leading "=" (n8n expression marker) is ignored. The path drops the query string.
    """
    if not isinstance(url, str):
        return None, None
    text = url[1:] if url.startswith("=") else url
    text = text.strip()
    for host in allowed_hosts:
        if text.startswith(host):
            rest = text[len(host):]
            if rest == "" or rest[0] in "/?":
                return host, rest.split("?", 1)[0] or "/"
    return None, None


def _http_method(parameters):
    method = parameters.get("method") or parameters.get("requestMethod") or "GET"
    return str(method).upper()


def audit_workflow(workflow, allowed_hosts=ALLOWED_HOSTS):
    """Describe relevant nodes and return (node_reports, violations, paths) for a workflow object."""
    node_reports = []
    violations = []
    paths = []
    nodes = workflow.get("nodes", [])
    if not isinstance(nodes, list):
        return [], ["workflow.nodes must be a list"], []
    outside_nodes = {key: value for key, value in workflow.items() if key != "nodes"}
    if "$env" in json.dumps(outside_nodes):
        violations.append("workflow: references $env outside nodes")
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            violations.append("nodes[{}] must be an object".format(index))
            continue
        name = node.get("name", "")
        label = name or "nodes[{}]".format(index)
        if "$env" in json.dumps(node):
            violations.append("{}: references $env".format(label))
        node_type = node.get("type", "")
        short_type = node_type.rsplit(".", 1)[-1]
        if short_type not in EXTERNAL_TYPES:
            continue
        parameters = node.get("parameters") or {}
        options = parameters.get("options") or {}
        retry = bool(node.get("retryOnFail", False))
        max_tries = node.get("maxTries")
        timeout = options.get("timeout") if isinstance(options, dict) else None
        report = {
            "name": name,
            "type": node_type,
            "onError": node.get("onError"),
            "retry": retry,
            "maxTries": max_tries,
            "timeout": timeout,
        }
        node_reports.append(report)
        if not node.get("onError"):
            violations.append("{}: external node has no onError".format(label))
        if retry:
            if isinstance(max_tries, bool) or not isinstance(max_tries, int) or max_tries > 3 or max_tries < 1:
                violations.append("{}: retryOnFail requires maxTries from 1 through 3".format(label))
        if short_type == "jira" and parameters.get("operation", "create") == "create" and retry:
            violations.append("{}: Jira create must have retryOnFail false".format(label))
        if short_type != "httpRequest":
            continue
        if not _positive_timeout(timeout):
            violations.append("{}: httpRequest has no positive options.timeout".format(label))
        method = _http_method(parameters)
        host, path = split_url(parameters.get("url"), allowed_hosts)
        report["method"] = method
        report["host"] = host
        if host is None:
            violations.append("{}: httpRequest URL is not under an allowed host".format(label))
            continue
        if host in PATH_TARGETS:
            paths.append({"node": label, "target": PATH_TARGETS[host], "method": method, "path": path})
        if host == "__JIRA_BASE_URL__" and method == "POST" and JIRA_CREATE_PATH.match(path) and retry:
            violations.append("{}: Jira create must have retryOnFail false".format(label))
    return node_reports, violations, paths


def check_file(path, allowed_hosts=ALLOWED_HOSTS):
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8")
    secrets = scan_secrets(text)
    workflow = json.loads(text)
    nodes, violations, paths = audit_workflow(workflow, allowed_hosts)
    return {
        "file": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "secrets": secrets,
        "nodes": nodes,
        "paths": paths,
        "violations": violations,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="exported n8n workflow JSON to inspect")
    parser.add_argument("--out", default="static_checks.json", help="JSON report path")
    parser.add_argument("--strict", action="store_true", help="exit non-zero when secrets or violations exist")
    parser.add_argument("--allowed-hosts", default=",".join(ALLOWED_HOSTS),
                        help="comma-separated URL prefixes every httpRequest URL must start with")
    args = parser.parse_args(argv)
    allowed_hosts = tuple(h.strip() for h in args.allowed_hosts.split(",") if h.strip())
    result = check_file(args.file, allowed_hosts)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(args.strict and bool(result["secrets"] or result["violations"]))


if __name__ == "__main__":
    sys.exit(main())
