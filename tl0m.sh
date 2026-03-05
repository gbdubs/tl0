#!/usr/bin/env bash
# Standalone entry point for tl0m (machine-facing CLI).
# Usage: ./tl0m.sh <command> [args...]
# Or symlink: ln -s /path/to/tl0/tl0m.sh /usr/local/bin/tl0m

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$SCRIPT_DIR" exec python3 -m tl0.cli_machine "$@"
