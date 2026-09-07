#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root. Builds are sequential because they use port 80.
export PATH="$PWD/utils:$PATH"
export DOCKER_TAG="${DOCKER_TAG:-branch-main}"
export DOCKER_IMAGE="${DOCKER_IMAGE:-ghcr.io/dataspecer/ws:$DOCKER_TAG}"
exports_dir="$PWD/exports"

docker pull "$DOCKER_IMAGE"
shopt -s nullglob
for directory in specifications/*/; do
  directory="${directory%/}"
  echo "Building $directory"
  (
    export EXPORT_DIR="$exports_dir/${directory#specifications/}"
    mkdir -p "$EXPORT_DIR"
    cd "$directory"
    if [[ -f build.sh ]]; then
      bash -e build.sh
    else
      build.sh
    fi
  )
done
