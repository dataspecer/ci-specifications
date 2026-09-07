#!/usr/bin/env bash

set -euo pipefail

rm -rf -- backup xml

archive="$(mktemp)"
checkout="$(mktemp -d)"
trap 'rm -f -- "$archive"; rm -rf -- "$checkout"' EXIT

curl -fL \
	-o "$archive" \
	"https://github.com/techlib/CCMM/raw/refs/heads/2.0.0/Czech%20Core%20Metadata%20Model-backup.zip"

unzip -q "$archive" \
	-d backup

git clone \
	--depth 1 \
	--single-branch \
	--branch sample-data-2.0 \
	-- "https://github.com/techlib/CCMM.git" \
	"$checkout/repository"

cp -a -- "$checkout/repository/_metadata-samples/xml" xml/