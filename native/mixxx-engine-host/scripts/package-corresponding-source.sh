#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
host_root="$repo_root/native/mixxx-engine-host"
mixxx_commit=3ebac449e7e5fe2a0186596657696e87ce8b0e56
gsl_commit=a3534567187d2edc428efd3f13466ff75fe5805c
version="$(node -p "require('$repo_root/src-tauri/tauri.conf.json').version")"
output_dir="${1:-$repo_root/src-tauri/target/release/bundle/dmg}"
output="$output_dir/plumdeck_${version}_Mixxx_corresponding_source.tar.gz"

[[ "$(git -C "$host_root/upstream" rev-parse HEAD)" == "$mixxx_commit" ]]
[[ -z "$(git -C "$host_root/upstream" status --porcelain)" ]]
[[ "$(git -C "$host_root/build-deps/gsl" rev-parse HEAD)" == "$gsl_commit" ]]
[[ -z "$(git -C "$host_root/build-deps/gsl" status --porcelain)" ]]

mkdir -p "$output_dir"
work="$(mktemp -d "$output_dir/.corresponding-source.XXXXXX")"
trap 'rm -rf -- "$work"' EXIT
root="$work/plumdeck_${version}_Mixxx_corresponding_source"
mkdir -p "$root/mixxx" "$root/GSL" "$root/plumdeck-adapter"

git -C "$host_root/upstream" archive "$mixxx_commit" | tar -x -C "$root/mixxx"
git -C "$host_root/build-deps/gsl" archive "$gsl_commit" | tar -x -C "$root/GSL"
ldc="$host_root/build-deps/libdatachannel"
ldc_commit=20bf658a60881854984f8ffb1586a4722bf590ec
[[ "$(git -C "$ldc" rev-parse HEAD)" == "$ldc_commit" ]]
[[ -z "$(git -C "$ldc" status --porcelain -- . ':(exclude)build-static')" ]]
mkdir -p "$root/libdatachannel"
git -C "$ldc" archive "$ldc_commit" | tar -x -C "$root/libdatachannel"
# git archive omits submodule contents; include each exact gitlink revision.
while read -r mode type commit subpath; do
  [[ "$mode" == 160000 ]] || continue
  [[ "$(git -C "$ldc/$subpath" rev-parse HEAD)" == "$commit" ]]
  [[ -z "$(git -C "$ldc/$subpath" status --porcelain)" ]]
  mkdir -p "$root/libdatachannel/$subpath"
  git -C "$ldc/$subpath" archive "$commit" | tar -x -C "$root/libdatachannel/$subpath"
done < <(git -C "$ldc" ls-tree -r "$ldc_commit")
[[ "$(brew list --versions opus)" == 'opus 1.6.1' ]]
opus_archive="$work/opus-1.6.1.tar.gz"
curl --fail --location --proto '=https' --tlsv1.2 --output "$opus_archive" https://ftp.osuosl.org/pub/xiph/releases/opus/opus-1.6.1.tar.gz
[[ "$(shasum -a 256 "$opus_archive" | cut -d ' ' -f 1)" == 6ffcb593207be92584df15b32466ed64bbec99109f007c82205f0194572411a1 ]]
tar -xzf "$opus_archive" -C "$root"
nice_archive="$work/libnice-0.1.23.tar.gz"
curl --fail --location --proto '=https' --tlsv1.2 --output "$nice_archive" https://libnice.freedesktop.org/releases/libnice-0.1.23.tar.gz
[[ "$(shasum -a 256 "$nice_archive" | cut -d ' ' -f 1)" == 618fc4e8de393b719b1641c1d8eec01826d4d39d15ade92679d221c7f5e4e70d ]]
tar -xzf "$nice_archive" -C "$root"
soundtouch_archive="$work/soundtouch-2.4.1.tar.gz"
curl --fail --location --proto '=https' --tlsv1.2 --output "$soundtouch_archive" https://codeberg.org/soundtouch/soundtouch/archive/2.4.1.tar.gz
[[ "$(shasum -a 256 "$soundtouch_archive" | cut -d ' ' -f 1)" == 35d404e6e8c2ebd12fb4000da6fadd75c99e37eed2126a04721828c11c0377ec ]]
tar -xzf "$soundtouch_archive" -C "$root"
rubberband_archive="$work/rubberband-4.0.0.tar.bz2"
curl --fail --location --proto '=https' --tlsv1.2 --output "$rubberband_archive" https://breakfastquay.com/files/releases/rubberband-4.0.0.tar.bz2
[[ "$(shasum -a 256 "$rubberband_archive" | cut -d ' ' -f 1)" == af050313ee63bc18b35b2e064e5dce05b276aaf6d1aa2b8a82ced1fe2f8028e9 ]]
tar -xjf "$rubberband_archive" -C "$root"
samplerate_archive="$work/libsamplerate-0.2.2.tar.xz"
curl --fail --location --proto '=https' --tlsv1.2 --output "$samplerate_archive" https://github.com/libsndfile/libsamplerate/releases/download/0.2.2/libsamplerate-0.2.2.tar.xz
[[ "$(shasum -a 256 "$samplerate_archive" | cut -d ' ' -f 1)" == 3258da280511d24b49d6b08615bbe824d0cacc9842b0e4caf11c52cf2b043893 ]]
tar -xJf "$samplerate_archive" -C "$root"
/usr/bin/ditto "$host_root/src" "$root/plumdeck-adapter/src"
/usr/bin/ditto "$host_root/cmake" "$root/plumdeck-adapter/cmake"
/usr/bin/ditto "$host_root/scripts" "$root/plumdeck-adapter/scripts"
cp "$host_root/CMakeLists.txt" "$root/plumdeck-adapter/CMakeLists.txt"
cp "$repo_root/README.md" "$root/README.md"
cp "$host_root/dependency-versions.json" "$root/dependency-versions.json"

formulae="$(node -p "Object.keys(require('$host_root/dependency-versions.json').homebrew).join(' ')")"
# Homebrew's JSON records each formula's license, homepage, source URL and
# installed version. It intentionally over-includes build-only dependencies so
# every library that may have entered the staged runtime has provenance.
# shellcheck disable=SC2086
brew info --json=v2 $formulae > "$root/HOMEBREW_FORMULAE.json"

stage_frameworks="$host_root/stage/PlumdeckMixxxHost.app/Contents/Frameworks"
if [[ -d "$stage_frameworks" ]]; then
  find "$stage_frameworks" -type f -print | sed "s#^$stage_frameworks/##" | sort \
    > "$root/BUNDLED_RUNTIME_FILES.txt"
fi

cat > "$root/SOURCE_MANIFEST.txt" <<EOF
plumdeck version: $version
plumdeck source: https://github.com/Yutahhhhh/plumdeck/tree/v$version
Mixxx source: https://github.com/mixxxdj/mixxx/commit/$mixxx_commit
Mixxx commit: $mixxx_commit
Microsoft GSL source: https://github.com/microsoft/GSL/commit/$gsl_commit
Microsoft GSL commit: $gsl_commit

The build entry point is plumdeck-adapter/scripts/build-macos.sh. It fetches the
same pinned sources and records all build options used for the distributed host.
EOF

tar -czf "$work/source.tar.gz" -C "$work" "$(basename "$root")"
mv -f -- "$work/source.tar.gz" "$output"
shasum -a 256 "$output"
