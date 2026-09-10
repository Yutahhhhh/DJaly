#!/bin/bash
set -euo pipefail
exec node "$(dirname "$0")/../scripts/project.mjs" backend-install
