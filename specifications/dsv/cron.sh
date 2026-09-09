#!/usr/bin/env bash

set -euo pipefail

archive="$(mktemp)"
trap 'rm -f -- "$archive"' EXIT

curl -fL \
	-o "$archive" \
	"https://github.com/mff-uk/data-specification-vocabulary/raw/refs/heads/main/dsv/Data%20Specification%20Vocabulary%20(DSV).zip"

rm -rf -- backup
unzip -q "$archive" \
	-d backup
