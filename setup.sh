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
# Use uv pip compile + sync to ensure all transitive dependencies are resolved
rm -f uv.lock
uv sync --reinstall


# ---------- data ----------
DATA_FILE="data/medcalc_sample.jsonl"
mkdir -p data
if [ ! -f "$DATA_FILE" ]; then
  echo "Data not found. Downloading data..."
  # Feed script on stdin ('-') and forward CLI flags after it
  python - "$@" <<'PY'
import sys, subprocess
subprocess.check_call([sys.executable, "src/download_data.py", *sys.argv[1:]])
PY
  echo "Data download complete."
else
  echo "Data already exists at $DATA_FILE. Skipping download."
fi

# ---------- Java 17 (for FHIR validator) ----------
if command -v java &> /dev/null; then
  JAVA_VERSION=$(java -version 2>&1 | head -n 1 | awk -F '"' '{print $2}' | awk -F '.' '{print $1}')
  if [ "$JAVA_VERSION" -ge 17 ] 2>/dev/null; then
    echo "Java $JAVA_VERSION is already installed."
  else
    echo "Java $JAVA_VERSION found but need Java 17+. Installing..."
    sudo apt-get update -qq
    sudo apt-get install -y openjdk-17-jdk
  fi
else
  echo "Java not found. Installing OpenJDK 17..."
  sudo apt-get update -qq
  sudo apt-get install -y openjdk-17-jdk
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
  bun install
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

# run tests where they live
echo "[test] Running bun test in kiln-headless/server..."
export TERMINOLOGY_DB_PATH="$(pwd)/db/terminology.sqlite"
export VALIDATOR_JAR="$(pwd)/validator.jar"
bun test || echo "[warn] bun test failed or no tests found; continuing"

cd ..
