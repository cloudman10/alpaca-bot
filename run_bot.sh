#!/bin/bash
# Wrapper for Bot 2 — captures exit code so healthcheck can distinguish
# a clean shutdown (code 0) from a real crash (non-zero).
# Healthcheck reads logs/last_exit_code before deciding whether to restart.

cd ~/Desktop/alpaca-bot
/opt/homebrew/bin/python3 ~/Desktop/alpaca-bot/main.py >> ~/Desktop/alpaca-bot/logs/bot.log 2>&1
EXIT_CODE=$?
echo "$EXIT_CODE" > ~/Desktop/alpaca-bot/logs/last_exit_code
exit $EXIT_CODE
