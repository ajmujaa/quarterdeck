#!/bin/bash
# Builds ~/Applications/QuarterdeckAgenda.app. A bundle with its own identity is what
# lets macOS ask for Calendar and Reminders access in the app's own name, even when
# the dashboard (a background service) is the one that starts it.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
app="$HOME/Applications/QuarterdeckAgenda.app"
rm -rf "$app"; mkdir -p "$app/Contents/MacOS"
swiftc -O "$here/main.swift" -o "$app/Contents/MacOS/QuarterdeckAgenda"
cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>dev.quarterdeck.agenda</string>
  <key>CFBundleName</key><string>QuarterdeckAgenda</string>
  <key>CFBundleExecutable</key><string>QuarterdeckAgenda</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
  <key>NSCalendarsFullAccessUsageDescription</key><string>Quarterdeck shows today's events on your dashboard. They stay on this Mac.</string>
  <key>NSRemindersFullAccessUsageDescription</key><string>Quarterdeck shows your reminders on your dashboard. They stay on this Mac.</string>
</dict></plist>
PLIST
codesign --force --sign - --identifier dev.quarterdeck.agenda "$app"
echo "built $app"
