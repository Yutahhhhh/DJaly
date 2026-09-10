#!/usr/bin/env bash
set -euo pipefail
host_root="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
checkpoint_root="$host_root/build-deps/rubberband"
mkdir -p "$checkpoint_root/build-config"
if [[ ! -f "$checkpoint_root/source.tar.bz2" ]]; then
 curl --fail --location --proto '=https' --tlsv1.2 https://breakfastquay.com/files/releases/rubberband-4.0.0.tar.bz2 -o "$checkpoint_root/source.tar.bz2"
fi
if [[ ! -f "$checkpoint_root/samplerate.tar.xz" ]]; then
 curl --fail --location --proto '=https' --tlsv1.2 https://github.com/libsndfile/libsamplerate/releases/download/0.2.2/libsamplerate-0.2.2.tar.xz -o "$checkpoint_root/samplerate.tar.xz"
fi
python3 "$host_root/scripts/prepare-rubberband-checkpoint.py" "$checkpoint_root" "$host_root/src/junction"
cp "$host_root/cmake/rubberband-source.cmake" "$checkpoint_root/build-config/CMakeLists.txt"
cmake -S "$checkpoint_root/build-config" -B "$checkpoint_root/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 \
 -DRB_SOURCE="$checkpoint_root/source" -DRB_ADAPTER="$host_root/src/junction" -DRB_PRIVATE="$checkpoint_root/private"
cmake --build "$checkpoint_root/build" --parallel "${PLUMDECK_BUILD_JOBS:-4}"
