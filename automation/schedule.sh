#!/bin/sh
# Schedule the Indian trader skills on this Mac with launchd (Mon-Fri, IST clock).
#
#   ./schedule.sh install "/path/to/data folder"   # folder that holds trader/
#   ./schedule.sh remove
#   ./schedule.sh status
#
# Jobs: 08:35 login reminder, 08:45 pre-market brief, ORB + news at 09:40,
# 10:10, 10:40, 11:10, 12:10, 13:10, 14:10, evening filings at 22:15.
# The Mac must be awake (lid open or plugged in with sleep off) for a job to run;
# launchd runs a missed job when the Mac wakes. Times use the Mac's clock,
# so keep its time zone on India (IST).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
HOME_DIR="$HOME/.trader-india"
AGENTS="$HOME/Library/LaunchAgents"
PREFIX="com.indian-trader-skills"
PY=$(command -v python3)

job() {  # name mode "HH:MM HH:MM ..."
  name=$1; mode=$2; times=$3; plist="$AGENTS/$PREFIX.$name.plist"
  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    echo '<plist version="1.0"><dict>'
    echo "  <key>Label</key><string>$PREFIX.$name</string>"
    echo "  <key>ProgramArguments</key><array><string>$PY</string><string>-I</string>"
    echo "    <string>$HOME_DIR/trader_day.py</string><string>$mode</string>"
    echo "    <string>--data</string><string>$DATA</string></array>"
    echo "  <key>WorkingDirectory</key><string>$DATA</string>"
    echo "  <key>StandardOutPath</key><string>$HOME_DIR/logs/$name.log</string>"
    echo "  <key>StandardErrorPath</key><string>$HOME_DIR/logs/$name.log</string>"
    echo "  <key>StartCalendarInterval</key><array>"
    for t in $times; do
      for d in 1 2 3 4 5; do
        echo "    <dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>${t%%:*}</integer><key>Minute</key><integer>${t##*:}</integer></dict>"
      done
    done
    echo "  </array>"
    echo '</dict></plist>'
  } > "$plist"
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist"
  echo "scheduled $name: $times (Mon-Fri)"
}

case "$1" in
  install)
    DATA=${2:?usage: ./schedule.sh install "/path/to/data folder"}
    DATA=$(cd "$DATA" && pwd)
    mkdir -p "$HOME_DIR/logs" "$AGENTS"
    cp "$HERE/trader_day.py" "$HOME_DIR/trader_day.py"
    job reminder  reminder  "08:35"
    job premarket premarket "08:45"
    job orb       orb       "09:40 10:10 10:40 11:10 12:10 13:10 14:10"
    job evening   evening   "22:15"
    echo "Reports go to: $DATA/trader/reports/ (latest.md is the newest)"
    [ "$(date +%Z)" = "IST" ] || echo "warning: this Mac's time zone is $(date +%Z), not IST: job times follow the Mac's clock"
    ;;
  remove)
    for f in "$AGENTS/$PREFIX".*.plist; do
      [ -e "$f" ] || continue
      launchctl unload "$f" 2>/dev/null || true; rm -f "$f"; echo "removed $(basename "$f")"
    done
    ;;
  status)
    launchctl list | grep "$PREFIX" || echo "no jobs scheduled"
    ;;
  *)
    sed -n 2,13p "$0"; exit 2 ;;
esac
