#!/bin/sh
# Every tool this repo needs, on macOS or Linux. Uses nothing the checkout provides.
#
#   ./dev install          install what is missing
#   ./dev install --check  report only; exit 1 if anything is missing
set -eu

CHECK=0
[ "${1:-}" = --check ] && CHECK=1
missing=0
os=$(uname -s)

have() { command -v "$1" >/dev/null 2>&1; }

need() {  # need <tool> <macOS install> <Linux install>
  if have "$1"; then echo "✓ $1"; return 0; fi
  echo "✗ $1"
  missing=1
  [ "$CHECK" = 1 ] && return 0
  if [ "$os" = Darwin ]; then
    have brew || { echo "  install Homebrew first: https://brew.sh"; return 0; }
    echo "  → $2"; sh -c "$2"
  else
    echo "  → $3"; sh -c "$3"
  fi
}

need git  "brew install git"  "sudo apt-get install -y git"
need curl "brew install curl" "sudo apt-get install -y curl"
need lsof "brew install lsof" "sudo apt-get install -y lsof"
need uv   "brew install uv"   "curl -LsSf https://astral.sh/uv/install.sh | sh"
need docker "brew install --cask docker" "curl -fsSL https://get.docker.com | sh"

if have docker && ! docker info >/dev/null 2>&1; then
  echo "· docker is installed but not running — start Docker Desktop (or the docker service)"
  missing=1
fi
[ "$CHECK" = 1 ] && exit "$missing"
# Installing is not the same as installed: re-check, so a failed or skipped install exits non-zero.
for t in git curl lsof uv docker; do have "$t" || { echo "✗ $t is still missing (a new shell may be needed for PATH)"; exit 1; }; done
docker info >/dev/null 2>&1 || { echo '✗ docker is not running'; exit 1; }
uv sync
