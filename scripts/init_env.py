"""Create or complete .env from .env.example. Never prints values; never overwrites a non-empty value.

Random values for local-only tokens; documented defaults for non-secrets; OPENAI_API_KEY is left for you to paste.
Usage: python3 scripts/init_env.py
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RANDOM = {"T4_WEBHOOK_TOKEN": 32, "T4_WEBHOOK_PATH": 24, "SINK_TOKEN": 32, "JIRA_SANDBOX_API_TOKEN": 32,
          "SLACK_SANDBOX_BOT_TOKEN": 32}
DEFAULTS = {
    "T4_TARGET": "local", "N8N_BASE_URL": "http://localhost:5678", "N8N_CONTAINER": "n8n",
    "SINK_PORT": "8790", "SINK_BASE_URL": "http://host.docker.internal:8790",
    "JIRA_BASE_URL": "http://host.docker.internal:8790", "JIRA_SANDBOX_EMAIL": "t4-triage-bot@example.com",
    "JIRA_PROJECT_KEY": "SUP", "SLACK_BASE_URL": "http://host.docker.internal:8790",
    "SLACK_CHANNEL_TRIAGE": "C0T4TRIAGE", "SLACK_CHANNEL_REVIEW": "C0T4REVIEW",
    "LLM_PRICE_IN_PER_MTOK": "0.15", "LLM_PRICE_OUT_PER_MTOK": "0.60",
    "RUN_USD_CAP": "0.25", "DAILY_USD_CAP": "1.00", "PROJECT_LLM_USD_CAP": "2.00",
}


def main():
    names = [l.split("=", 1)[0].strip() for l in (ROOT / ".env.example").read_text().splitlines()
             if "=" in l and not l.lstrip().startswith("#")]
    env_path = ROOT / ".env"
    current = {}
    if env_path.exists():
        for l in env_path.read_text().splitlines():
            if "=" in l and not l.lstrip().startswith("#"):
                k, v = l.split("=", 1)
                current[k.strip()] = v.strip()
    filled, kept, empty = [], [], []
    for name in names:
        if current.get(name):
            kept.append(name)
        elif name in RANDOM:
            current[name] = secrets.token_urlsafe(RANDOM[name])
            filled.append(name)
        elif name in DEFAULTS:
            current[name] = DEFAULTS[name]
            filled.append(name)
        else:
            current.setdefault(name, "")
            empty.append(name)
    lines = ["{}={}".format(k, current.get(k, "")) for k in names]
    lines += ["{}={}".format(k, v) for k, v in current.items() if k not in names]
    env_path.write_text("\n".join(lines) + "\n")
    os.chmod(env_path, 0o600)
    print(".env written (mode 600). filled: {}. kept: {}. still empty: {}.".format(
        len(filled), len(kept), ", ".join(empty) or "none"))
    if empty:
        print("Paste a value for each empty name with your editor, e.g. OPENAI_API_KEY (not echoed here).")


if __name__ == "__main__":
    main()
