#!/bin/bash
# Buduje BrainGestures.app. Aplikacja uruchamia silnik z ../tools (tools/.venv musi istniec).
set -euo pipefail
cd "$(dirname "$0")"
TOOLS="$(cd ../tools && pwd)"
[ -x "$TOOLS/.venv/bin/python" ] || { echo "Brak $TOOLS/.venv - utworz srodowisko wg tools/README.md"; exit 1; }

swift build -c release
APP="build/BrainGestures.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/release/BrainGestures "$APP/Contents/MacOS/BrainGestures"
cat > "$APP/Contents/Resources/engine.json" <<JSON
{"python": "$TOOLS/.venv/bin/python", "script": "$TOOLS/engine.py"}
JSON
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>BrainGestures</string>
  <key>CFBundleDisplayName</key><string>BrainGestures</string>
  <key>CFBundleIdentifier</key><string>dev.neurohackathon.braingestures</string>
  <key>CFBundleExecutable</key><string>BrainGestures</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSBluetoothAlwaysUsageDescription</key>
  <string>BrainGestures laczy sie z czepkiem BrainAccess przez Bluetooth, aby odczytywac sygnal EEG.</string>
</dict>
</plist>
PLIST
codesign --force --sign - "$APP" >/dev/null
echo "Gotowe: $(pwd)/$APP"
