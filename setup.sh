#!/bin/bash
# setup.sh — run once after cloning to activate git hooks
git config core.hooksPath .githooks
echo "Git hooks activated. Pre-commit hook will auto-update TRADING_BOTS.md on every commit."
