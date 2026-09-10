#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
bundle="${1:-$repo_root/src-tauri/target/release/bundle/macos/plumdeck.app}"
version="$(node -e 'console.log(JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).version)' "$repo_root/src-tauri/tauri.conf.json")"
machine_arch="$(uname -m)"
case "$machine_arch" in
  arm64) bundle_arch=aarch64 ;;
  x86_64) bundle_arch=x64 ;;
  *) echo "Unsupported macOS architecture: $machine_arch" >&2; exit 1 ;;
esac
dmg_dir="$(dirname "$(dirname "$bundle")")/dmg"
output="$dmg_dir/plumdeck_${version}_${bundle_arch}.dmg"

[[ -d "$bundle" ]] || { echo "Missing signed app bundle: $bundle" >&2; exit 1; }
codesign --verify --deep --strict "$bundle"

work="$(mktemp -d "$dmg_dir/.performance-dmg.XXXXXX")"
mount_point=""
cleanup() {
  if [[ -n "$mount_point" ]] && mount | grep -Fq "on $mount_point "; then
    hdiutil detach "$mount_point" >/dev/null || true
  fi
  rm -rf -- "$work"
}
trap cleanup EXIT

mkdir -p "$work/payload"
/usr/bin/ditto "$bundle" "$work/payload/plumdeck.app"
ln -s /Applications "$work/payload/Applications"

hdiutil create -quiet -volname "plumdeck $version" -srcfolder "$work/payload" \
  -format UDZO -ov "$work/plumdeck.dmg"
hdiutil verify "$work/plumdeck.dmg" >/dev/null

mount_point="$work/mount"
mkdir -p "$mount_point"
hdiutil attach -readonly -nobrowse -mountpoint "$mount_point" "$work/plumdeck.dmg" >/dev/null
nested="$mount_point/plumdeck.app/Contents/Resources/PlumdeckMixxxHost.app"
[[ -x "$nested/Contents/MacOS/plumdeck-mixxx-engine-host" ]] || {
  echo "Repacked DMG does not contain the Mixxx host" >&2
  exit 1
}
codesign --verify --deep --strict "$mount_point/plumdeck.app"
hdiutil detach "$mount_point" >/dev/null
mount_point=""

mv -f -- "$work/plumdeck.dmg" "$output"
echo "Verified Performance DMG: $output"
