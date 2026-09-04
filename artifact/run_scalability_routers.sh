#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
exec bash "${SCRIPT_DIR}/run_scalability_common.sh" routers "${1:-fast}"
