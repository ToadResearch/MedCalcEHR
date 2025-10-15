#!/usr/bin/env bash
set -euo pipefail

# Ensure tools are in PATH
export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"

# Activate venv (in case we need any Python tools)
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

base_url="http://127.0.0.1:30000/v1"
model="baichuan-m2-32b-gptq-int4"

cd kiln-headless

bun run headless --batch \
  --file ../data/medcalc_sample.jsonl \
  --column "Patient Note" \
  --type note \
  --result-dir output \
  --result-file sample_out.jsonl \
  --llm-url $base_url \
  --model $model \
  --llm-max-concurrency 16 \
  --val-max-iters 30 \
  --fhir-concurrency 5 \
  --no-api-key