#!/usr/bin/env bash
# Backward compatibility wrapper - actual script moved to tools/media/watermark_shorts.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/tools/media/watermark_shorts.sh" "$@"
