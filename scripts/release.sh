#!/bin/bash
set -euo pipefail
if [[ "${1:-}" == "--skip-upload" ]]; then
  exec node "$(dirname "$0")/project.mjs" package
fi
exec node "$(dirname "$0")/project.mjs" release "$@"
