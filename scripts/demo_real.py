"""Owner-run checks for the real Jira/Slack demo (close plan §4, D-1). Agents do not run this file.

  python3 scripts/demo_real.py check    # Jira project keys, create fields, Slack bot auth
  python3 scripts/demo_real.py count    # issues per t4 dedupe label in the demo project (replay proof)

Reads *_REAL_* names from .env. Prints keys, counts and field names only, never tokens. Standard library only.
"""
import base64
import collections
import json
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("JIRA_REAL_BASE_URL", "JIRA_REAL_EMAIL", "JIRA_REAL_API_TOKEN", "JIRA_REAL_PROJECT_KEY",
         "SLACK_REAL_BOT_TOKEN", "SLACK_REAL_CHANNEL_TRIAGE", "SLACK_REAL_CHANNEL_REVIEW")
NEEDED_FIELDS = ("summary", "description", "labels", "priority")


def env():
    out = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    missing = [n for n in NAMES if not out.get(n)]
    if missing:
        sys.exit("not set in .env: " + ", ".join(missing))
    return out


def call(url, headers, data=None):
    req = Request(url, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode() or "{}")


def jira(e, path):
    auth = base64.b64encode("{}:{}".format(e["JIRA_REAL_EMAIL"], e["JIRA_REAL_API_TOKEN"]).encode()).decode()
    return call(e["JIRA_REAL_BASE_URL"].rstrip("/") + path, {"Authorization": "Basic " + auth,
                                                              "Accept": "application/json"})


def check(e):
    ok = True
    keys = [p["key"] for p in jira(e, "/rest/api/3/project/search?maxResults=50").get("values", [])]
    print("jira projects visible to the bot:", ", ".join(keys) or "none")
    key = e["JIRA_REAL_PROJECT_KEY"]
    if key not in keys:
        print("FAIL: JIRA_REAL_PROJECT_KEY is not one of these keys")
        return 1
    types = jira(e, "/rest/api/3/issue/createmeta/{}/issuetypes".format(quote(key))).get("issueTypes", [])
    task = [t for t in types if t["name"] == "Task"]
    print("issue types:", ", ".join(t["name"] for t in types))
    if not task:
        print("FAIL: no 'Task' issue type (workflow config jira_issue_type=Task)")
        return 1
    fields = jira(e, "/rest/api/3/issue/createmeta/{}/issuetypes/{}".format(quote(key), task[0]["id"]))
    have = {f.get("fieldId") for f in fields.get("fields", fields.get("values", []))}
    for f in NEEDED_FIELDS:
        print("field {}: {}".format(f, "ok" if f in have else "MISSING on the create screen"))
        ok &= f in have
    slack = call("https://slack.com/api/auth.test", {"Authorization": "Bearer " + e["SLACK_REAL_BOT_TOKEN"]}, {})
    print("slack bot auth:", "ok" if slack.get("ok") else "FAIL " + str(slack.get("error")))
    ok &= bool(slack.get("ok"))
    print("PREFLIGHT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def count(e):
    jql = 'project = "{}" AND labels = "t4"'.format(e["JIRA_REAL_PROJECT_KEY"])
    issues = jira(e, "/rest/api/3/search/jql?fields=labels&maxResults=100&jql=" + quote(jql)).get("issues", [])
    per = collections.Counter(l for i in issues for l in i["fields"]["labels"] if l.startswith("t4dk-"))
    print("t4 issues:", len(issues), "| distinct dedupe labels:", len(per))
    dupes = {k: n for k, n in per.items() if n > 1}
    print("max issues per dedupe label:", max(per.values()) if per else 0, "| duplicates:", len(dupes))
    return 1 if dupes else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "count"):
        sys.exit(__doc__)
    sys.exit({"check": check, "count": count}[cmd](env()))
