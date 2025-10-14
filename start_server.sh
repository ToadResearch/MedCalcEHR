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
    --port 30000 \
    --tp 4 \
    --dp 2 \
    --dtype bfloat16 \
    --reasoning-parser qwen3 \
    --mem-fraction 0.9 \
    --cuda-graph-max-bs 2 \
    --kv-cache-dtype fp8_e4m3 \
    --attention-backend flashinfer \
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
