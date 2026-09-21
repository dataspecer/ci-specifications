#!/usr/bin/env bash

set -euo pipefail

archive="$(mktemp)"
trap 'rm -f -- "$archive"' EXIT

curl -fL \
	-o "$archive" \
	"https://github.com/datagov-cz/otevrene-formalni-normy/raw/refs/heads/main/dcat-ap-cz-hvd/2026-09-23/DCAT-AP-CZ%20Datov%C3%A9%20sady%20s%20vysokou%20hodnotou%20(HVD)-backup.zip"

rm -rf -- backup
unzip -q "$archive" \
	-d backup
