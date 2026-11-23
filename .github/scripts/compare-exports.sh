#!/usr/bin/env bash
set -euo pipefail

: "${EXPORT_TOKEN:?Set the EXPORT_REPOSITORY_TOKEN secret}"
: "${DOCKER_TAG:?}"
: "${BASE_EXPORT_TAG:?}"
if [[ ! "$EXPORT_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo 'Invalid EXPORT_REPOSITORY; expected owner/repository' >&2
  exit 1
fi
git check-ref-format --branch "$DOCKER_TAG" >/dev/null
git check-ref-format --branch "$BASE_EXPORT_TAG" >/dev/null

# Keep export credentials scoped to fetching snapshots, separate from commenting.
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=http.https://github.com/.extraheader
export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$EXPORT_TOKEN" | base64 -w0)"
export GIT_TERMINAL_PROMPT=0
unset EXPORT_TOKEN

comparison_dir="$(mktemp -d "$RUNNER_TEMP/compare.XXXXXX")"
git init --quiet "$comparison_dir"
cd "$comparison_dir"
git remote add origin "https://github.com/${EXPORT_REPOSITORY}.git"

# Fetch only after all publishers finish, so a faster PR cannot use an old baseline.
git fetch --depth=1 --no-tags origin "refs/heads/$DOCKER_TAG"
git update-ref HEAD FETCH_HEAD
baseline=()
if git ls-remote --exit-code --heads origin "refs/heads/$BASE_EXPORT_TAG" > /dev/null; then
  git fetch --depth=1 --no-tags origin "refs/heads/$BASE_EXPORT_TAG"
  baseline=(FETCH_HEAD)
else
  status=$?
  if [[ "$status" != 2 ]]; then
    echo 'Could not query comparison baseline' >&2
    exit "$status"
  fi
fi
python3 "$GITHUB_WORKSPACE/.github/scripts/comment-export.py" report "${baseline[@]}"
