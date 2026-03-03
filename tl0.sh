#!/usr/bin/env bash
# Standalone entry point — no pip install needed.
# Usage: ./tl0.sh <command> [args...]
# Or symlink: ln -s /path/to/tl0/tl0.sh /usr/local/bin/tl0

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$SCRIPT_DIR" exec python3 -m tl0.cli "$@"
