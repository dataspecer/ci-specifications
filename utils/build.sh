#!/usr/bin/env bash
set -euo pipefail

: "${EXPORT_DIR:?Set EXPORT_DIR to the absolute output directory for this specification}"
image="${DOCKER_IMAGE:-ghcr.io/dataspecer/ws:${DOCKER_TAG:-branch-main}}"
work_dir="$(mktemp -d)"
container_id=''

cleanup() {
  if [[ -n "$container_id" ]]; then
    docker stop "$container_id" >/dev/null || true
  fi
  rm -rf -- "$work_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -f backup.zip ]]; then
  cp backup.zip "$work_dir/backup.zip"
else
  (cd backup && zip -qr "$work_dir/backup.zip" .)
fi
# Read the resource directory from the actual archive being imported.
iri="$(unzip -Z1 "$work_dir/backup.zip" | sed 's@^\./@@' | awk -F/ 'NF > 1 && $1 != "" {print $1}' | sort -u)"
if [[ -z "$iri" || "$iri" == *$'\n'* ]]; then
  echo 'Backup must contain exactly one top-level resource directory' >&2
  exit 1
fi
docker pull "$image"
container_id="$(docker run --detach --rm --publish 127.0.0.1:80:80 "$image")"

base_url='http://127.0.0.1:80'
deadline=$((SECONDS + 30))
while true; do
  remaining=$((deadline - SECONDS))
  if ((remaining <= 0)); then
    echo 'Container did not return ok from /health within 30 seconds' >&2
    docker logs "$container_id" >&2 || true
    exit 1
  fi
  timeout=$((remaining < 2 ? remaining : 2))
  if response="$(curl --fail --silent --max-time "$timeout" "$base_url/health")" && [[ "$response" == ok ]]; then
    break
  fi
  if ((SECONDS < deadline)); then
    sleep 1
  fi
done

curl --fail --show-error --silent --location --output /dev/null \
  --form "file=@$work_dir/backup.zip;type=application/zip" \
  "$base_url/api/resources/import-zip"
curl --fail --show-error --silent --location \
  --get --data-urlencode "iri=$iri" \
  --output "$work_dir/output.zip" \
  "$base_url/api/experimental/output.zip"
mkdir -p "$EXPORT_DIR"
unzip -qo "$work_dir/output.zip" -d "$EXPORT_DIR"
(cd "$EXPORT_DIR" && cleanup-export.sh)
