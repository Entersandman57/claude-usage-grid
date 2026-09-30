#!/bin/bash
# Phase 0 probe (b): one minimal headless call in a launchd-like clean environment.
# Prints the rate_limit_event lines and result metadata; keeps no reply text.
# Override the binary with CLAUDE_BIN=/path/to/claude.
set -u
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)/out"
mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%dT%H%M%S)"
RAW="$(mktemp -t meter-probe)"

cd "$OUT_DIR" || exit 1
env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  LANG=en_US.UTF-8 CLAUDE_USAGE_GRID_METER=1 \
  "$CLAUDE_BIN" -p "Reply with the single word: ok" \
  --model haiku --no-session-persistence \
  --output-format stream-json --verbose \
  --tools "" --strict-mcp-config \
  --system-prompt "Reply with exactly one word." --max-turns 1 \
  < /dev/null > "$RAW" 2> "$OUT_DIR/meter-probe-$STAMP.stderr"
echo "exit=$?"

# Sanitized copy: rate-limit events plus result metadata, no assistant text.
jq -c 'select(.type == "rate_limit_event")
       , (select(.type == "result")
          | {type, subtype, is_error, total_cost_usd, duration_ms,
             error: (if .is_error then .result else null end)})' \
  "$RAW" | tee "$OUT_DIR/meter-probe-$STAMP.jsonl"
rm -f "$RAW"
