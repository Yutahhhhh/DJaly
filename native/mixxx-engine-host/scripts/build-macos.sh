#!/usr/bin/env bash
set -euo pipefail
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
fetch_pinned https://github.com/mixxxdj/mixxx.git "$mixxx_commit" "$host_root/upstream"
fetch_pinned https://github.com/microsoft/GSL.git "$gsl_commit" "$host_root/build-deps/gsl"
brew_prefix="$(brew --prefix)"
protobuf_prefix="$(brew --prefix protobuf)"
abseil_prefix="$(brew --prefix abseil)"
mkdir -p "$host_root/logs"
cmake -S "$host_root/upstream" -B "$host_root/build-upstream" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$brew_prefix" \
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
cmake --build "$host_root/build-upstream" --target djaly-mixxx-engine-host --parallel "${DJALY_BUILD_JOBS:-6}" \
  2>&1 | tee "$host_root/logs/build.log"
