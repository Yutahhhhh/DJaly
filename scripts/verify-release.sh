#!/bin/bash
set -euo pipefail
exec node "$(dirname "$0")/project.mjs" pre-release
