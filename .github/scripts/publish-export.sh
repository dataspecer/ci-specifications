#!/usr/bin/env bash
set -euo pipefail

: "${EXPORT_TOKEN:?Set the EXPORT_REPOSITORY_TOKEN secret}"
: "${EXPORT_DIR:?}"
: "${DOCKER_TAG:?}"
if [[ ! "$EXPORT_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo 'Invalid EXPORT_REPOSITORY; expected owner/repository' >&2
  exit 1
fi
git check-ref-format --branch "$DOCKER_TAG" >/dev/null

# Keep credentials out of the URL, persisted Git configuration, and build jobs.
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=http.https://github.com/.extraheader
export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$EXPORT_TOKEN" | base64 -w0)"
export GIT_TERMINAL_PROMPT=0
unset EXPORT_TOKEN

publication_dir="$(mktemp -d "$RUNNER_TEMP/publish.XXXXXX")"
git init --quiet "$publication_dir"
cd "$publication_dir"
git remote add origin "https://github.com/${EXPORT_REPOSITORY}.git"
git config user.name 'github-actions[bot]'
git config user.email 'github-actions[bot]@users.noreply.github.com'

if git ls-remote --exit-code --heads origin "refs/heads/$DOCKER_TAG" > /dev/null; then
  git fetch --depth=1 --filter=blob:none --no-tags origin "refs/heads/$DOCKER_TAG"
  # Attach HEAD without checking out old files (which would download their blobs).
  git update-ref "refs/heads/$DOCKER_TAG" FETCH_HEAD
  git symbolic-ref HEAD "refs/heads/$DOCKER_TAG"
else
  status=$?
  if [[ "$status" != 2 ]]; then
    echo 'Could not query export repository' >&2
    exit "$status"
  fi
  git checkout --orphan "$DOCKER_TAG"
fi

# Replace the entire snapshot, including files removed since the previous build.
git read-tree --empty
cp -a "$EXPORT_DIR/." .
git add --all --force
python3 - <<'PY'
import json
import os
from pathlib import Path

event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
inputs = event.get('inputs') or {}
if os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch':
    title = inputs['source_commit_title'].split('\n')[0]
    subject = f"{title} ({inputs['source_commit'][:7]})"
else:
    title = (event.get('head_commit') or {}).get('message', 'Specifications updated').split('\n')[0]
    subject = f"[ci-specifications repo] {title} ({os.environ['GITHUB_SHA'][:7]})"
lines = [subject, '']
lines += [f"Docker image: {os.environ['DOCKER_IMAGE']}"]
if inputs.get('source_commit'):
    lines += [f"Application commit: {inputs['source_commit']}"]
if inputs.get('source_repository'):
    lines += [f"Application repository: {inputs['source_repository']}"]
if inputs.get('pr_number') or inputs.get('pr_title'):
    lines += [f"Pull request: #{inputs.get('pr_number', '')} {inputs.get('pr_title', '')}"]
lines += [f"Specifications: {os.environ['GITHUB_REPOSITORY']}@{os.environ['GITHUB_SHA']}",
          f"Workflow: {os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
          f"Run attempt: {os.environ['GITHUB_RUN_ATTEMPT']}"]
Path(os.environ['RUNNER_TEMP'], 'export-commit-message.txt').write_text('\n'.join(lines) + '\n')
PY
# Even identical output records that this source revision was built.
# Suppress the diff summary so Git does not fetch old blobs to compute statistics.
git commit --quiet --allow-empty --file "$RUNNER_TEMP/export-commit-message.txt"
git push origin "HEAD:refs/heads/$DOCKER_TAG"

# Generate the PR report while export-repository credentials are available.
if [[ "$GITHUB_EVENT_NAME" == workflow_dispatch ]] && \
   python3 -c 'import json, os, sys; sys.exit(not json.load(open(os.environ["GITHUB_EVENT_PATH"])).get("inputs", {}).get("pr_number"))'; then
  baseline=()
  if git ls-remote --exit-code --heads origin refs/heads/branch-main > /dev/null; then
    git fetch --depth=1 --no-tags origin refs/heads/branch-main
    baseline=(FETCH_HEAD)
  else
    status=$?
    if [[ "$status" != 2 ]]; then
      echo 'Could not query comparison baseline' >&2
      exit "$status"
    fi
  fi
  python3 "$GITHUB_WORKSPACE/.github/scripts/comment-export.py" report "${baseline[@]}"
fi
