#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

OUTPUT_DIR="storage/transcripts"
LANGUAGE="id"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -l|--languages|--language)
      LANGUAGE="$2"
      shift 2
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      VIDEO_PATH="$1"
      shift
      ;;
  esac
done

if [[ -z "${VIDEO_PATH:-}" ]]; then
  echo "Usage: $0 [-o output_dir] [-l language] <video_path>" >&2
  exit 1
fi

# Extract video ID from video path
VIDEO_FILENAME=$(basename "$VIDEO_PATH")
VIDEO_ID=$(echo "$VIDEO_FILENAME" | grep -oE '[A-Za-z0-9_-]{11}' | tail -n 1)

if [[ -z "$VIDEO_ID" ]]; then
  echo "ERROR: Could not extract 11-character video ID from $VIDEO_FILENAME" >&2
  exit 1
fi

# Make output directory absolute if it is not
if [[ ! "$OUTPUT_DIR" =~ ^/ ]]; then
  OUTPUT_DIR="$REPO_ROOT/$OUTPUT_DIR"
fi

TRANSCRIPT_DIR="$OUTPUT_DIR/$VIDEO_ID"
mkdir -p "$TRANSCRIPT_DIR"

AUDIO_PATH="$TRANSCRIPT_DIR/audio.wav"
WORD_TIMESTAMPS_PATH="$TRANSCRIPT_DIR/word_timestamps.json"

# Find python interpreter
PYTHON_BIN="$REPO_ROOT/.venv-transcript-api/bin/python"
if [[ -n "${SUBTITLE_AUTOCAPTIONS_PYTHON:-}" ]]; then
  PYTHON_BIN="$SUBTITLE_AUTOCAPTIONS_PYTHON"
fi

if [[ ! -f "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$REPO_ROOT/.venv-transcript-api/bin/python"
fi

if [[ ! -f "$PYTHON_BIN" ]]; then
  echo "ERROR: Python env with whisper not found at $PYTHON_BIN" >&2
  exit 1
fi

echo "Running Whisper auto-captions generator..."
echo "  Video ID: $VIDEO_ID"
echo "  Video Path: $VIDEO_PATH"
echo "  Output Directory: $TRANSCRIPT_DIR"
echo "  Language: $LANGUAGE"

"$PYTHON_BIN" "$REPO_ROOT/external_packages/auto-captions/caption_generator.py" \
  -i "$VIDEO_PATH" \
  -a "$AUDIO_PATH" \
  -o "$WORD_TIMESTAMPS_PATH" \
  -m "medium" \
  -l "$LANGUAGE" \
  --preset "accurate" \
  --audio-preset "speech" \
  --save-raw-result
