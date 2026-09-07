#!/usr/bin/env bash
set -euo pipefail
host_root="$(cd "$(dirname "$0")/.." && pwd)"
stage_root="$host_root/stage"
cmake -E make_directory "$stage_root"
staging_dir="$(mktemp -d "$stage_root/.staging.XXXXXX")"
bundle="$staging_dir/DJalyMixxxHost.app"
destination="$stage_root/DJalyMixxxHost.app"
qt_prefix="$(brew --prefix qtbase)"
cmake -E make_directory "$bundle/Contents/MacOS" "$bundle/Contents/Resources" "$bundle/Contents/PlugIns/platforms"
cmake -E copy_if_different "$host_root/build-upstream/djaly-mixxx-engine-host" "$bundle/Contents/MacOS/djaly-mixxx-engine-host"
cmake -E copy_if_different "$host_root/packaging/Info.plist" "$bundle/Contents/Info.plist"
cmake -E copy_directory "$host_root/upstream/res" "$bundle/Contents/Resources"
cmake -E copy_if_different "$qt_prefix/share/qt/plugins/platforms/libqoffscreen.dylib" "$bundle/Contents/PlugIns/platforms/libqoffscreen.dylib"
# This host never uses SQL/UI plugins. Only offscreen is needed; explicitly
# pass it so its complete dependency graph is rewritten and copied as well.
macdeployqt "$bundle" -no-plugins -always-overwrite -verbose=1 \
  -executable="$bundle/Contents/PlugIns/platforms/libqoffscreen.dylib"
node "$host_root/scripts/fix-stage-runtime.mjs" "$bundle"
codesign --force --deep --sign - "$bundle"
codesign --verify --deep --strict "$bundle"
otool -L "$bundle/Contents/MacOS/djaly-mixxx-engine-host"
# macOS directory exchange atomically promotes the complete, verified bundle.
# An existing bundle is preserved at the generated staging path, never deleted.
xcrun clang -Wall -Wextra -Werror "$host_root/scripts/promote-stage.c" -o "$staging_dir/promote-stage"
"$staging_dir/promote-stage" "$bundle" "$destination"
cmake -E copy_if_different "$staging_dir/runtime-audit.json" "$stage_root/runtime-audit.json"
echo "Staged executable: $destination/Contents/MacOS/djaly-mixxx-engine-host"
echo "Previous bundle (if any) preserved under: $staging_dir"
