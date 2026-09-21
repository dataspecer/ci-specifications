#!/usr/bin/env bash

set -euo pipefail

archive="$(mktemp)"
trap 'rm -f -- "$archive"' EXIT

curl -fL \
	-o "$archive" \
	"https://github.com/datagov-cz/otevrene-formalni-normy/raw/refs/heads/main/dcat-ap-cz-rozhran%C3%AD-katalog%C5%AF-dat/2026-09-23/DCAT-AP-CZ%20Rozhran%C3%AD%20katalog%C5%AF%20dat-backup.zip"

rm -rf -- backup
unzip -q "$archive" \
	-d backup
