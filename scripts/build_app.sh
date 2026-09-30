#!/bin/bash
# Build Claude Usage Grid (app + widget), sign it with your Personal Team,
# install it to /Applications and relaunch it.
#
#   scripts/build_app.sh            build, install, relaunch
#   scripts/build_app.sh test       run the Swift unit tests only
#
# The team comes from $DEVELOPMENT_TEAM, else from the Personal Team Xcode is signed into.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$REPO/app"
DERIVED="$REPO/build/DerivedData"
INSTALLED="/Applications/ClaudeUsageGrid.app"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

TEAM="${DEVELOPMENT_TEAM:-$(defaults read com.apple.dt.Xcode IDEProvisioningTeamByIdentifier 2>/dev/null \
  | awk -F' = ' '/teamID/ { gsub(/[; "]/, "", $2); print $2; exit }')}"
if [ -z "$TEAM" ]; then
  echo "No team found: add your Apple ID in Xcode > Settings > Accounts, or set DEVELOPMENT_TEAM." >&2
  exit 1
fi

cd "$APP_DIR"
DEVELOPMENT_TEAM="$TEAM" xcodegen generate --quiet

if [ "${1:-}" = "test" ]; then
  xcodebuild test -project ClaudeUsageGrid.xcodeproj -scheme SharedTests \
    -destination 'platform=macOS,arch=arm64' -derivedDataPath "$DERIVED" CODE_SIGNING_ALLOWED=NO 2>&1 \
    | grep -E "error:|Test Case .*failed|Executed .* tests|\*\* TEST" | sort -u
  exit "${PIPESTATUS[0]}"
fi

xcodebuild build -project ClaudeUsageGrid.xcodeproj -scheme ClaudeUsageGrid -configuration Release \
  -derivedDataPath "$DERIVED" -allowProvisioningUpdates -quiet DEVELOPMENT_TEAM="$TEAM"
BUILT="$DERIVED/Build/Products/Release/ClaudeUsageGrid.app"

# Replace the installed copy, and unregister the build copy so the widget
# gallery only ever sees the one in /Applications.
pkill -x ClaudeUsageGrid 2>/dev/null || true
rm -rf "$INSTALLED"
cp -R "$BUILT" "$INSTALLED"
"$LSREGISTER" -u "$BUILT" 2>/dev/null || true
"$LSREGISTER" -f "$INSTALLED"
open "$INSTALLED"
echo "Installed $INSTALLED (team $TEAM)"
