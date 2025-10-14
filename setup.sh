#!/usr/bin/env bash
set -euo pipefail

# ---------- uv + venv ----------
if ! command -v uv &>/dev/null; then
  echo "uv not found. Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# make a local venv on py3.12 (sglang-friendly)
if [ ! -d ".venv" ]; then
  echo "Creating Python 3.12 venv with uv..."
  uv venv --python 3.12 .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# sync project deps (sglang, datasets, flashinfer)
uv pip install --upgrade pip
uv sync


# --- Patch SGLang drafter for Baichuan M2 (MTP + speculative decoding) ---
patch_sglang_qwen2() {
  set -euo pipefail

  echo "Locating SGLang install..."
  SGLANG_DIR="$(python - <<'PY'
import inspect, os, sys
try:
    import sglang
except Exception as e:
    sys.exit("ERROR: sglang is not installed in this Python env.")
print(os.path.dirname(inspect.getfile(sglang)))
PY
  )"

  TARGET="${SGLANG_DIR}/srt/models/qwen2.py"
  BACKUP="${TARGET}.bak"

  if [ ! -f "$TARGET" ]; then
    echo "ERROR: Expected file not found: $TARGET"
    echo "Make sure SGLang is installed in this environment."
    return 1
  fi

  TMP_DIR="$(mktemp -d)"
  DL="${TMP_DIR}/qwen2.py"
  echo "Downloading Baichuan drafter (draft/qwen2.py) from Hugging Face..."
  # Using curl keeps this script self-contained; no extra Python deps needed.
  curl -fsSL -o "$DL" \
    "https://huggingface.co/baichuan-inc/Baichuan-M2-32B-GPTQ-Int4/resolve/main/draft/qwen2.py"

  if [ ! -s "$DL" ]; then
    echo "ERROR: Failed to download draft/qwen2.py"
    return 1
  fi

  # Skip if already identical
  if command -v sha256sum >/dev/null 2>&1; then
    if [ -f "$TARGET" ] && [ "$(sha256sum "$TARGET" | awk '{print $1}')" = "$(sha256sum "$DL" | awk '{print $1}')" ]; then
      echo "SGLang drafter already matches Baichuan draft/qwen2.py; nothing to do."
      rm -rf "$TMP_DIR"
      return 0
    fi
  fi

  # Backup once
  if [ ! -f "$BACKUP" ]; then
    echo "Creating backup at $BACKUP"
    cp -p "$TARGET" "$BACKUP"
  fi

  echo "Replacing $TARGET"
  cp -f "$DL" "$TARGET"

  # Quick smoke check: make sure the new file mentions 'Drafter' or MTP hooks
  if ! grep -qiE "Drafter|MTP|draft" "$TARGET"; then
    echo "WARNING: Replacement file doesn't look like a drafter; proceed with caution."
  fi

  rm -rf "$TMP_DIR"
  echo "Done patching SGLang drafter."
}

# Call it (safe to run multiple times)
patch_sglang_qwen2


# ---------- data ----------
DATA_FILE="data/medcalc_sample.jsonl"
mkdir -p data
if [ ! -f "$DATA_FILE" ]; then
  echo "Data not found. Downloading data..."
  python - <<'PY' "$@"
import sys, subprocess
subprocess.check_call([sys.executable, "src/download_data.py", *sys.argv[1:]])
PY
  echo "Data download complete."
else
  echo "Data already exists at $DATA_FILE. Skipping download."
fi

# ---------- bun / kiln-headless ----------
if ! command -v bun &> /dev/null; then
  echo "Bun not found. Installing bun..."
  curl -fsSL https://bun.sh/install | bash
  export PATH="$HOME/.bun/bin:$PATH"
  echo "Bun installed successfully."
else
  echo "Bun is already installed."
fi

if [ ! -d "kiln-headless" ]; then
  echo "kiln-headless not found. Installing..."
  git clone https://github.com/ToadResearch/kiln-headless.git
  cd kiln-headless
  bun install
  echo "kiln-headless installed successfully."
else
  echo "kiln-headless is already installed."
  cd kiln-headless
fi

# Copy .env into kiln-headless
if [ -f "../.env" ]; then
  echo "Found .env file. Copying to kiln-headless/.env..."
  cp ../.env .env
else
  echo "ERROR: .env file not found in project root!"
  echo "Run: cp .env.example .env  (and set values)"
  exit 1
fi

# terminology setup
cd server
if [ -d "large-vocabularies" ] && [ ! -d "large-vocabularies/.git" ]; then
  echo "Removing empty large-vocabularies directory..."
  rm -rf large-vocabularies
fi
bun run scripts/setup.ts
bun add fast-xml-parser
bun run scripts/load-terminology.ts

cd ..
bun test