#!/usr/bin/env bash

set -euo pipefail

rm -rf -- "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/backup"

archive="$(mktemp)"
trap 'rm -f -- "$archive"' EXIT

curl -fL \
	-o "$archive" \
	"https://github.com/techlib/CCMM/raw/refs/heads/2.0.0/Czech%20Core%20Metadata%20Model-backup.zip"

unzip -q "$archive" \
	-d "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/backup"
