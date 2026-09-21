#!/usr/bin/env bash

set -euo pipefail

archive="$(mktemp)"
trap 'rm -f -- "$archive"' EXIT

curl -fL \
	-o "$archive" \
	"https://github.com/datagov-cz/otevrene-formalni-normy/raw/refs/heads/main/dcat-ap-cz/2026-09-23/DCAT-AP-CZ%20Z%C3%A1kladn%C3%AD%20datov%C3%BD%20model%20pro%20katalogy%20dat-backup.zip"

rm -rf -- backup
unzip -q "$archive" \
	-d backup
