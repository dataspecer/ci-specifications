#!/usr/bin/env bash
set -euo pipefail

: "${EXPORT_DIR:?Set EXPORT_DIR to the absolute output directory for this specification}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/../.." && pwd)"
export PATH="$repo_dir/utils:$PATH"

cd "$script_dir"
"$repo_dir/utils/build.sh"

mkdir -p "$EXPORT_DIR/_xml"
cp -a "$script_dir/xml/." "$EXPORT_DIR/_xml/"
find "$EXPORT_DIR/_xml" -type f -name '*.xml' -exec sed -i \
  's|https://raw\.githubusercontent\.com/techlib/CCMM/refs/heads/2\.0\.0|..|g' {} +

roundtrip_image="metadata-roundtrip:latest"
docker build --tag "$roundtrip_image" "$repo_dir/tools/roundtrip"
mkdir -p "$EXPORT_DIR/_roundtrip"
while IFS= read -r -d '' input; do
  relative_input="${input#"$EXPORT_DIR/"}"
  report="_roundtrip/${relative_input#_xml/}"
  echo "Roundtrip: $relative_input -> ${report%.xml}"
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$EXPORT_DIR,dst=/workspace" \
    --env ROUNDTRIP_REPO=/workspace \
    --env ROUNDTRIP_SCHEMA=dataset/schema.xsd \
    --env ROUNDTRIP_LIFTING=dataset/lifting.xslt \
    --env ROUNDTRIP_LOWERING=dataset/lowering.xslt \
    --env ROUNDTRIP_SHACL=shacl.ttl \
    --env ROUNDTRIP_BASE_IRI=urn:roundtrip:base: \
    --env ROUNDTRIP_SCHEMA_LOCATIONS= \
    --env ROUNDTRIP_FAIL_ON=pipeline \
    --env "ROUNDTRIP_INPUT=$relative_input" \
    --env "ROUNDTRIP_OUTPUT=${report%.xml}" \
    "$roundtrip_image"
done < <(find "$EXPORT_DIR/_xml" -type f -name '*.xml' -print0 | sort -z)
