#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
[[ "$(uname -m)" == arm64 && "$(brew --prefix)" == /opt/homebrew ]] || { echo "The release host requires ARM64 Homebrew at /opt/homebrew." >&2; exit 1; }
host_root="$(cd "$(dirname "$0")/.." && pwd)"
mixxx_commit=3ebac449e7e5fe2a0186596657696e87ce8b0e56
gsl_commit=a3534567187d2edc428efd3f13466ff75fe5805c
fetch_pinned() {
  local repository="$1" revision="$2" destination="$3"
  if [[ ! -d "$destination/.git" ]]; then
    git init "$destination"
    git -C "$destination" remote add origin "$repository"
    git -C "$destination" fetch --depth 1 origin "$revision"
    git -C "$destination" switch --detach FETCH_HEAD
  fi
  [[ "$(git -C "$destination" rev-parse HEAD)" == "$revision" ]] || { echo "Wrong revision: $destination" >&2; exit 1; }
  [[ -z "$(git -C "$destination" status --porcelain)" ]] || { echo "Modified dependency: $destination" >&2; exit 1; }
}
if [[ -d "$host_root/upstream/.git" ]] && git -C "$host_root/upstream" apply --reverse --check "$host_root/patches/recording-frame-clock.patch" 2>/dev/null; then
  git -C "$host_root/upstream" apply --reverse "$host_root/patches/recording-frame-clock.patch" || true
fi
fetch_pinned https://github.com/mixxxdj/mixxx.git "$mixxx_commit" "$host_root/upstream"
fetch_pinned https://github.com/microsoft/GSL.git "$gsl_commit" "$host_root/build-deps/gsl"
git -C "$host_root/upstream" apply --check "$host_root/patches/recording-frame-clock.patch"
git -C "$host_root/upstream" apply "$host_root/patches/recording-frame-clock.patch"
bash "$host_root/scripts/build-junction-deps.sh"
brew_prefix="$(brew --prefix)"
protobuf_prefix="$(brew --prefix protobuf)"
abseil_prefix="$(brew --prefix abseil)"
mkdir -p "$host_root/logs"
cmake -S "$host_root/upstream" -B "$host_root/build-upstream" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_PREFIX_PATH="$brew_prefix" \
  -DPKG_CONFIG_EXECUTABLE=/opt/homebrew/bin/pkg-config -DCMAKE_IGNORE_PREFIX_PATH=/usr/local \
  -DOPENSSL_ROOT_DIR=/opt/homebrew/opt/openssl@3 \
  -DOPENSSL_INCLUDE_DIR=/opt/homebrew/opt/openssl@3/include \
  -DOPENSSL_CRYPTO_LIBRARY=/opt/homebrew/opt/openssl@3/lib/libcrypto.dylib \
  -DOPENSSL_SSL_LIBRARY=/opt/homebrew/opt/openssl@3/lib/libssl.dylib \
  -DCMAKE_PROJECT_mixxx_INCLUDE="$host_root/cmake/inject-host.cmake" \
  -DCMAKE_NO_SYSTEM_FROM_IMPORTED=ON \
  "-DCMAKE_CXX_FLAGS=-I$host_root/build-deps/gsl/include -I$protobuf_prefix/include -I$abseil_prefix/include" \
  "-DCMAKE_OBJCXX_FLAGS=-I$host_root/build-deps/gsl/include -I$protobuf_prefix/include -I$abseil_prefix/include" \
  -DQT_TRANSLATION_FILE="$brew_prefix/share/qt/translations/qt_de.qm" \
  -DQML=OFF -DBUILD_TESTING=OFF -DBUILD_BENCH=OFF -DENGINEPRIME=OFF \
  -DKEYFINDER=OFF -DPORTMIDI=OFF -DAU_EFFECTS=OFF -DMACOS_ITUNES_LIBRARY=OFF \
  -DBROADCAST=OFF -DQTKEYCHAIN=OFF -DHID=OFF -DBULK=OFF -DVINYLCONTROL=OFF \
  -DFFMPEG=OFF -DBATTERY=OFF -DOPUS=OFF -DMAD=OFF -DMODPLUG=OFF -DLILV=OFF -DWAVPACK=OFF \
  2>&1 | tee "$host_root/logs/configure.log"
cmake --build "$host_root/build-upstream" --target plumdeck-mixxx-engine-host --parallel "${PLUMDECK_BUILD_JOBS:-6}" \
  2>&1 | tee "$host_root/logs/build.log"
