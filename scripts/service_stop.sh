#!/bin/bash
# Stop and disable the auto-start background service
launchctl unload ~/Library/LaunchAgents/com.sxbet.bot.plist 2>/dev/null
echo "SX Bet Bot service stopped."
