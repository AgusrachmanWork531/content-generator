#!/usr/bin/env bash
# Backward compatibility wrapper - actual script moved to tools/youtube/transcribe_youtube.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/tools/youtube/transcribe_youtube.sh" "$@"
