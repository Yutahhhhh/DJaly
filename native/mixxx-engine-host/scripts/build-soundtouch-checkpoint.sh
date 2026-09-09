#!/usr/bin/env bash
set -euo pipefail
host_root="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
checkpoint_root="$host_root/build-deps/soundtouch"
mkdir -p "$checkpoint_root"
if [[ ! -f "$checkpoint_root/source.tar.gz" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 https://codeberg.org/soundtouch/soundtouch/archive/2.4.1.tar.gz -o "$checkpoint_root/source.tar.gz"
fi
python3 "$host_root/scripts/prepare-soundtouch-checkpoint.py" "$checkpoint_root"
cmake -S "$checkpoint_root/source" -B "$checkpoint_root/build" -G Ninja \
 -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
 -DBUILD_SHARED_LIBS=OFF -DSOUNDSTRETCH=OFF -DSOUNDTOUCH_DLL=OFF -DOPENMP=OFF -DNEON=OFF
cmake --build "$checkpoint_root/build" --parallel "${DJALY_BUILD_JOBS:-4}"
