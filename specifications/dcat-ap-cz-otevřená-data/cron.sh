#!/usr/bin/env bash

set -euo pipefail

archive="$(mktemp)"
trap 'rm -f -- "$archive"' EXIT

curl -fL \
	-o "$archive" \
	"https://github.com/datagov-cz/otevrene-formalni-normy/raw/refs/heads/main/dcat-ap-cz-otev%C5%99en%C3%A1-data/2026-09-23/DCAT-AP-CZ%20Datov%C3%A9%20sady%20otev%C5%99en%C3%BDch%20dat-backup.zip"

rm -rf -- backup
unzip -q "$archive" \
	-d backup
