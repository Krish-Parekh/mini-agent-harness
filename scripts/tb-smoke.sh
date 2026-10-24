#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: scripts/tb-smoke.sh <terminal-bench-2 checkout> [harbor run options]" >&2
  exit 2
fi

dataset=$1
shift

tasks=(
  fix-git
  regex-log
  sqlite-db-truncate
  polyglot-c-py
  pypi-server
  nginx-request-logging
  build-pmars
  qemu-alpine-ssh
)
include=()
for task in "${tasks[@]}"; do
  include+=(-i "$task")
done

exec uv run harbor run \
  -p "$dataset" \
  -a miniagent.harbor:MiniAgent \
  -m anthropic/claude-sonnet-5-5 \
  -n 4 \
  "${include[@]}" \
  "$@"
