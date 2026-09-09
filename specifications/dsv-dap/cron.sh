#!/usr/bin/env bash

set -euo pipefail

archive="$(mktemp)"
trap 'rm -f -- "$archive"' EXIT

curl -fL \
	-o "$archive" \
	"https://github.com/mff-uk/data-specification-vocabulary/raw/refs/heads/main/dsv-dap/Data%20Specification%20Vocabulary%20-%20Default%20Application%20Profile%20(DSV-DAP)-backup.zip"

rm -rf -- backup
unzip -q "$archive" \
	-d backup
