#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root.
shopt -s nullglob
for directory in specifications/*/; do
  [[ -f "${directory}cron.sh" ]] || continue
  echo "Running ${directory}cron.sh"
  (cd "$directory" && bash -e cron.sh)
done
