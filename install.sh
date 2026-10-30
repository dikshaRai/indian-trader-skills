#!/bin/sh
# Copy the skills into Claude Code's skills folder. Safe to rerun after a pull.
set -e
cd "$(dirname "$0")"
mkdir -p "$HOME/.claude/skills"
for s in skills/*/; do
  name=$(basename "$s")
  mkdir -p "$HOME/.claude/skills/$name"
  cp "$s"*.py "$s"SKILL.md "$HOME/.claude/skills/$name/"
  echo "installed $name"
done
chmod +x "$HOME/.claude/skills/trader-scanner-india/kite_login.py"
command -v pdftotext >/dev/null || echo "tip: brew install poppler (to read NSE filing PDFs)"
echo "Restart Claude Code to load the skills."
