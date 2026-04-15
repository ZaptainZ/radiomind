#!/bin/bash
# Clean up RadioMind test sandboxes that accumulate in /tmp.
# Run: bash scripts/cleanup_sandboxes.sh
#
# What's preserved:
#   - /tmp/rm-test-venv  (Python venv for running tests)
#   - /tmp/rm-lora-test  (trained LoRA adapter + habit data)
# What's removed:
#   - All other /tmp/rm-* (per-test scratch dirs)
#   - LoRA numbered checkpoints (adapters.safetensors is the promoted final)
#   - Fused safetensors + GGUF deploy artifacts (re-derivable from adapter)
#   - /tmp/rm-hf-cache if present (duplicate of ~/.cache/huggingface)

set -e

KEEP=(rm-test-venv rm-lora-test)

echo "=== Before ==="
du -sh /tmp/rm-* 2>/dev/null | head

for d in /tmp/rm-*; do
    name=$(basename "$d")
    keep=0
    for k in "${KEEP[@]}"; do
        [ "$name" = "$k" ] && keep=1
    done
    if [ "$keep" -eq 0 ]; then
        rm -rf "$d"
    fi
done

# Numbered LoRA checkpoints (adapters.safetensors is the promoted final)
find /tmp/rm-lora-test/models/lora/adapters -name "00000*_adapters.safetensors" -delete 2>/dev/null || true
rm -rf /tmp/rm-lora-test/models/lora/fused 2>/dev/null || true
rm -f /tmp/rm-lora-test/models/lora/model.gguf 2>/dev/null || true

echo
echo "=== After ==="
du -sh /tmp/rm-* 2>/dev/null | head
df -h / | head -2
