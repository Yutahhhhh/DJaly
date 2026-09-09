#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
bundle="${1:-$repo_root/src-tauri/target/release/bundle/macos/Djaly.app}"
case "$bundle" in
  "$repo_root"/src-tauri/target/debug/bundle/macos/Djaly.app|"$repo_root"/src-tauri/target/release/bundle/macos/Djaly.app|"$repo_root"/src-tauri/target/release/bundle/macos/"Djaly Preview.app") ;;
  *) echo "Refusing to sign an unexpected bundle path: $bundle" >&2; exit 2 ;;
esac

nested="$bundle/Contents/Resources/DJalyMixxxHost.app"
staged="$repo_root/native/mixxx-engine-host/stage/DJalyMixxxHost.app"
[[ -x "$staged/Contents/MacOS/djaly-mixxx-engine-host" ]] || {
  echo "Staged Mixxx host is missing: $staged" >&2
  exit 1
}

# Tauri's generic resource copier dereferences framework symlinks. Install the
# already-audited nested app after bundling with ditto, which preserves the
# framework topology and extended attributes. `nested` is an exact generated
# path beneath the validated Djaly.app target above.
rm -rf -- "$nested"
/usr/bin/ditto "$staged" "$nested"

# Tauri's resource copier may materialize framework symlinks, invalidating the
# already-sealed nested app. Re-seal the nested app, then its containing app.
# '-' is local ad-hoc signing only; public distribution still requires the
# project's Developer ID + notarization workflow.
identity="${APPLE_SIGNING_IDENTITY:--}"
codesign --force --deep --sign "$identity" "$nested"
codesign --force --deep --sign "$identity" "$bundle"
codesign --verify --deep --strict "$nested"
codesign --verify --deep --strict "$bundle"
echo "Verified Performance bundle: $bundle"

if [[ "$bundle" == "$repo_root/src-tauri/target/release/bundle/macos/Djaly.app" ]]; then
  "$repo_root/native/mixxx-engine-host/scripts/repack-performance-dmg-macos.sh"
fi
