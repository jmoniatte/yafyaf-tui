#!/bin/bash
# Install/reinstall yafyaf-tui as a uv tool

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Uninstalling existing version..."
uv tool uninstall yafyaf-tui 2>/dev/null || true

echo "Clearing uv cache..."
uv cache clean

echo "Installing from $SCRIPT_DIR..."
uv tool install "$SCRIPT_DIR" --force --reinstall

echo "Done. Run 'yaf' to start."
