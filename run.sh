#!/usr/bin/env bash
# Backward compatibility wrapper - actual script moved to tools/service/run.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/tools/service/run.sh" "$@"
