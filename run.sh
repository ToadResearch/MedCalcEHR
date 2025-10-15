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

bun run headless --single \
  --text "Mr. Grok Four is 42 years old and has a stomach bug" \
  --type note_and_fhir \
  --llm-url $base_url \
  --model $model \
  --llm-max-concurrency 3 \
  --val-max-iters 30 \
  --fhir-concurrency 3 \
  --no-api-key 

bun run headless --batch \
  --file example-batch/sample.jsonl \
  --column "context" \
  --type note \
  --result-dir output \
  --result-file sample_out.jsonl \
  --llm-url $base_url \
  --model $model \
  --llm-max-concurrency 3 \
  --val-max-iters 30 \
  --fhir-concurrency 3 \
  --no-api-key