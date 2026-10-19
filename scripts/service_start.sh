#!/bin/bash
# Start and enable the auto-start background service
launchctl unload ~/Library/LaunchAgents/com.sxbet.bot.plist 2>/dev/null
launchctl load -w ~/Library/LaunchAgents/com.sxbet.bot.plist
echo "SX Bet Bot service started and enabled on startup."
