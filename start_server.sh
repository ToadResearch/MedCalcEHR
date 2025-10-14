#!/usr/bin/env bash
set -euo pipefail

# Activate project venv
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Defaults
if [ $# -eq 0 ]; then
  set -- \
    --model-path baichuan-inc/Baichuan-M2-32B-GPTQ-Int4 \
    --served-model-name baichuan-m2-32b-gptq-int4 \
    --host 0.0.0.0 \
    --port 30000 \
    --tp 8 \
    --dtype bfloat16 \
    --kv-cache-dtype fp8_e4m3 \
    "$ATTN_FLAG" flashinfer \
    --mem-fraction-static 0.9 \
    --cuda-graph-max-bs 2 \
    --reasoning-parser qwen3 \
    --speculative-algorithm EAGLE3 \
    --speculative-draft-model-path baichuan-inc/Baichuan-M2-32B-GPTQ-Int4/draft \
    --speculative-num-steps 6 \
    --speculative-eagle-topk 10 \
    --speculative-num-draft-tokens 32
fi

echo "Launching SGLang with:"
printf '  %q' python3 -m sglang.launch_server
printf ' %q' "$@"
echo

python3 -m sglang.launch_server "$@"
