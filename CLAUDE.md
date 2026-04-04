## MANDATORY RULE — Always Update TRADING_BOTS.md
Every time you make ANY code change to this project, you MUST:
1. Add a new row to the "Optimization History" table in TRADING_BOTS.md with:
   - Date (today's date)
   - What changed (file and specific change)
   - Why it was changed (the reason/problem it solves)
   - Result (✅ Done, or outcome if known)
2. Update the "Current Entry Logic" section if entry/exit conditions changed
3. Commit TRADING_BOTS.md in the same commit as the code change
4. Never make a code commit without updating TRADING_BOTS.md

This is non-negotiable. Every change must be documented.

## New Machine Setup
After cloning on a new machine, run: bash setup.sh to activate the auto-update hooks.

## Windows Path Format
When running bash commands on Windows, ALWAYS use Unix-style paths:
- ✅ Correct: /c/Users/Admin/alpaca-bot
- ❌ Wrong: C:\Users\Admin\alpaca-bot

Windows machine folder locations:
- Bot 1 (trading-bot): /c/Users/Admin/trading-bot
- Bot 2 (alpaca-bot): /c/Users/Admin/alpaca-bot

Mac machine folder locations:
- Bot 1 (trading-bot): ~/TradingApp
- Bot 2 (alpaca-bot): ~/Desktop/alpaca-bot

NEVER clone a repo without first running ls to verify the folder doesn't already exist.
