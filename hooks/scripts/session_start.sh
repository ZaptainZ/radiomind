#!/usr/bin/env bash
# RadioMind SessionStart Hook — inject context digest.
# Only used when RadioHeader is NOT installed (RadioHeader has its own loader).

if ! command -v radiomind &>/dev/null; then
  exit 0
fi

echo "RadioMind ready"

# Inject context digest
DIGEST=$(radiomind status 2>/dev/null | grep -A 100 "Context Digest:" | tail -n +2)
if [ -n "$DIGEST" ]; then
  echo ""
  echo "--- radiomind context ---"
  echo "$DIGEST"
  echo "--- end context ---"
fi
