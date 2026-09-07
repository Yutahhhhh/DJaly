#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
host_root="$repo_root/native/mixxx-engine-host"
mixxx_commit=3ebac449e7e5fe2a0186596657696e87ce8b0e56
gsl_commit=a3534567187d2edc428efd3f13466ff75fe5805c
version="$(node -p "require('$repo_root/src-tauri/tauri.conf.json').version")"
output_dir="${1:-$repo_root/src-tauri/target/release/bundle/dmg}"
output="$output_dir/Djaly_${version}_Mixxx_corresponding_source.tar.gz"

[[ "$(git -C "$host_root/upstream" rev-parse HEAD)" == "$mixxx_commit" ]]
[[ -z "$(git -C "$host_root/upstream" status --porcelain)" ]]
[[ "$(git -C "$host_root/build-deps/gsl" rev-parse HEAD)" == "$gsl_commit" ]]
[[ -z "$(git -C "$host_root/build-deps/gsl" status --porcelain)" ]]

mkdir -p "$output_dir"
work="$(mktemp -d "$output_dir/.corresponding-source.XXXXXX")"
trap 'rm -rf -- "$work"' EXIT
root="$work/Djaly_${version}_Mixxx_corresponding_source"
mkdir -p "$root/mixxx" "$root/GSL" "$root/djaly-adapter"

git -C "$host_root/upstream" archive "$mixxx_commit" | tar -x -C "$root/mixxx"
git -C "$host_root/build-deps/gsl" archive "$gsl_commit" | tar -x -C "$root/GSL"
/usr/bin/ditto "$host_root/src" "$root/djaly-adapter/src"
/usr/bin/ditto "$host_root/cmake" "$root/djaly-adapter/cmake"
/usr/bin/ditto "$host_root/scripts" "$root/djaly-adapter/scripts"
cp "$host_root/CMakeLists.txt" "$root/djaly-adapter/CMakeLists.txt"
cp "$repo_root/docs/dj-engine/licenses.md" "$root/THIRD_PARTY_NOTICES.md"
cp "$host_root/dependency-versions.json" "$root/dependency-versions.json"

formulae="$(node -p "Object.keys(require('$host_root/dependency-versions.json').homebrew).join(' ')")"
# Homebrew's JSON records each formula's license, homepage, source URL and
# installed version. It intentionally over-includes build-only dependencies so
# every library that may have entered the staged runtime has provenance.
# shellcheck disable=SC2086
brew info --json=v2 $formulae > "$root/HOMEBREW_FORMULAE.json"

stage_frameworks="$host_root/stage/DJalyMixxxHost.app/Contents/Frameworks"
if [[ -d "$stage_frameworks" ]]; then
  find "$stage_frameworks" -type f -print | sed "s#^$stage_frameworks/##" | sort \
    > "$root/BUNDLED_RUNTIME_FILES.txt"
fi

cat > "$root/SOURCE_MANIFEST.txt" <<EOF
Djaly version: $version
DJaly source: https://github.com/Yutahhhhh/DJaly/tree/v$version
Mixxx source: https://github.com/mixxxdj/mixxx/commit/$mixxx_commit
Mixxx commit: $mixxx_commit
Microsoft GSL source: https://github.com/microsoft/GSL/commit/$gsl_commit
Microsoft GSL commit: $gsl_commit

The build entry point is djaly-adapter/scripts/build-macos.sh. It fetches the
same pinned sources and records all build options used for the distributed host.
EOF

tar -czf "$work/source.tar.gz" -C "$work" "$(basename "$root")"
mv -f -- "$work/source.tar.gz" "$output"
shasum -a 256 "$output"
