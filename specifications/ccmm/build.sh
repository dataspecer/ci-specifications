#!/usr/bin/env bash
set -euo pipefail

specification_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export_dir="${EXPORT_DIR:-$specification_dir/../../exports}/ccmm"
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

# Archive the contents of backup, with the resource IRI at the ZIP root.
(cd "$specification_dir/backup" && zip -qr "$work_dir/backup.zip" .)
docker pull "$image"
container_id="$(docker run --detach --rm --publish 127.0.0.1:80:80 "$image")"

base_url='http://127.0.0.1:80'
deadline=$((SECONDS + 30))
while true; do
  remaining=$((deadline - SECONDS))
  if ((remaining <= 0)); then
    echo 'CCMM container did not return ok from /health within 30 seconds' >&2
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
  --get --data-urlencode 'iri=d54a372a-b13d-479f-b8d8-2ce4c9a06b25' \
  --output "$work_dir/output.zip" \
  "$base_url/api/experimental/output.zip"
mkdir -p "$export_dir"
unzip -qo "$work_dir/output.zip" -d "$export_dir"
(cd "$export_dir" && bash "$specification_dir/../../utils/cleanup-export.sh")
