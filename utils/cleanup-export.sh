#!/usr/bin/env bash
set -euo pipefail

find . -type f \( -name README.md -o -name '*.error.*' \) -delete
