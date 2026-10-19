#!/bin/bash
# Check status and show last 25 lines of log
echo "=== macOS LaunchAgent Status ==="
launchctl list | grep com.sxbet.bot || echo "Service not currently running."
echo ""
echo "=== Recent Bot Output (bot.log) ==="
tail -n 25 /Users/karimsiam/.gemini/antigravity/scratch/sx_betting_bot/bot.log
