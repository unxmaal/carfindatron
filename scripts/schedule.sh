#!/bin/bash
# Install, remove or check the daily carfindatron LaunchAgent: ./scripts/schedule.sh install [HH:MM] | remove | status | run
set -euo pipefail

LABEL=com.carfindatron.daily
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$HOME/.local/share/carfindatron"
UV="$(command -v uv)"
DOMAIN="gui/$(id -u)"

case "${1:-status}" in
install)
    at="${2:-07:15}"
    hour=$((10#${at%%:*})); minute=$((10#${at##*:}))
    mkdir -p "$DATA" "$(dirname "$PLIST")"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$UV</string><string>run</string><string>--project</string><string>$PROJECT</string>
        <string>carfindatron</string><string>--notify</string>
    </array>
    <key>WorkingDirectory</key><string>$PROJECT</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>$(dirname "$UV"):/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>$hour</integer><key>Minute</key><integer>$minute</integer></dict>
    <key>StandardOutPath</key><string>$DATA/daily.log</string>
    <key>StandardErrorPath</key><string>$DATA/daily.log</string>
    <key>ProcessType</key><string>Background</string>
</dict>
</plist>
EOF
    plutil -lint "$PLIST" >/dev/null
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "installed: daily at $(printf '%02d:%02d' "$hour" "$minute"), log $DATA/daily.log"
    ;;
remove)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed"
    ;;
run)
    launchctl kickstart -p "$DOMAIN/$LABEL"
    ;;
status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
        launchctl print "$DOMAIN/$LABEL" | grep -E "^\s(state|last exit code|runs) =" | sed 's/^[[:space:]]*//'
        grep -A1 "<key>Hour</key>" "$PLIST" | tr -d '\n' | sed -E 's/.*Hour<\/key><integer>([0-9]+).*Minute<\/key><integer>([0-9]+).*/schedule = daily at \1:\2/'; echo
    else
        echo "not installed"
    fi
    ;;
*) echo "usage: $0 install [HH:MM] | remove | status | run" >&2; exit 2 ;;
esac
