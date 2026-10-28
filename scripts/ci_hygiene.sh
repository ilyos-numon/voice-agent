#!/usr/bin/env bash
# Repository hygiene checks for CI (tracked files only).
# - no 4-octet IP address literal (lock files excluded)
# - no tracked .env / .env.* file (except .env.example)
# - no "sk-" token-like string of 32+ characters
# Prints file:line for each finding and exits 1 on failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail=0

octet='(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])'
ip_re="(^|[^0-9A-Za-z.])${octet}(\\.${octet}){3}([^0-9A-Za-z.]|\$)"
lock_excludes=(':(exclude)*.lock' ':(exclude)*-lock.json' ':(exclude)*-lock.yaml' ':(exclude)*.lockb')

if hits="$(git grep -nIE "$ip_re" -- . "${lock_excludes[@]}")"; then
  echo "hygiene: IP address literal found" >&2
  printf '%s\n' "$hits" | cut -d: -f1,2 >&2
  fail=1
fi

envs="$(git ls-files | grep -E '(^|/)\.env(\..+)?$' | grep -vE '(^|/)\.env\.example$' || true)"
if [ -n "$envs" ]; then
  echo "hygiene: tracked env file found" >&2
  printf '%s:1\n' $envs >&2
  fail=1
fi

if hits="$(git grep -nIE 'sk-[A-Za-z0-9_-]{29,}' -- .)"; then
  echo "hygiene: secret-like token found" >&2
  printf '%s\n' "$hits" | cut -d: -f1,2 >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  exit 1
fi
echo "hygiene: ok"
