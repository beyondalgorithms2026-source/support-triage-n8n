#!/usr/bin/env bash
# Guardrails run after every goal (and by hand any time):
#   secret patterns and .env values (names reported, never values) · .env untracked · logs redacted in place
#   no dependency manifests · stdlib-only imports · banned words in prose
#   protected files and outside-folder state unchanged since loop start (logs/outside_snapshot.json)
set -uo pipefail
cd "$(dirname "$0")/.."
python3 scripts/checks.py guard
