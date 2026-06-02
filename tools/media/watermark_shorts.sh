#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEFAULT_OUTPUT_DIR="storage/free-viral-shorts"
DEFAULT_WATERMARK_TEXT="@KilasanVideo"
DEFAULT_FFMPEG_FULL_BIN="/opt/homebrew/opt/ffmpeg-full/bin"
DEFAULT_FONT_PATH="assets/font/sheeping-cats-font/SheepingCatsStraight-lrlZ.ttf"
DEFAULT_LOGO_PATH=""

OUTPUT_DIR="${OUTPUT_DIR:-$DEFAULT_OUTPUT_DIR}"
WATERMARK_TEXT="${WATERMARK_TEXT:-$DEFAULT_WATERMARK_TEXT}"
MODE="text"
POSITION="center_15_top"
FONT_PATH="${FONT_PATH:-$DEFAULT_FONT_PATH}"
LOGO_PATH="${LOGO_PATH:-$DEFAULT_LOGO_PATH}"
SOURCE_TITLE="${SOURCE_TITLE:-}"
CONFIG_PATH=""
DRY_RUN=0
VIDEO_IDS=()

log() {
  printf '[watermark-shorts] %s\n' "$*" >&2
}

die() {
  printf '[watermark-shorts] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage:
  ./${SCRIPT_NAME} [options] <video-id-or-run-dir> [more-video-ids...]

What it does:
  Adds adaptive watermark to rendered shorts in:
  storage/free-viral-shorts/<VIDEO_ID>/shorts

Options:
  -o, --output-dir DIR       Base output dir. Default: ${DEFAULT_OUTPUT_DIR}
  --text TEXT                Watermark text. Default: ${DEFAULT_WATERMARK_TEXT}
  --font FILE                Font file. Default: ${DEFAULT_FONT_PATH}
  --logo FILE                Logo/image watermark file. Default: disabled
  --source-title TEXT        Source credit shown on the main video, not thumbnail
  --mode MODE                auto, safe_badge, split_safe, logo, text. Default: ${MODE}
  --position POSITION        auto, top_right, top_left, center_top, center_right,
                             center_left, center_bottom, bottom_right, bottom_left, center,
                             center_15_top.
                             Default: ${POSITION}
  --config FILE              Optional watermark_config.json
  --dry-run                  Build plan only, do not render video
  -h, --help                 Show this help

Examples:
  ./${SCRIPT_NAME} NSbnx60GCEI
  ./${SCRIPT_NAME} NSbnx60GCEI --text "@MyChannel" --mode text --position center_15_top
  ./${SCRIPT_NAME} NSbnx60GCEI --logo assets/watermark/logo.png --mode logo
  ./${SCRIPT_NAME} storage/free-viral-shorts/NSbnx60GCEI --text "@MyChannel"

Output:
  storage/free-viral-shorts/<VIDEO_ID>/watermark_plan.json
  storage/free-viral-shorts/<VIDEO_ID>/watermarked/short_01_wm.mp4
EOF
}

absolute_path() {
  local path="$1"
  if [ "${path#/}" != "$path" ]; then
    printf '%s\n' "$path"
    return
  fi
  printf '%s/%s\n' "$REPO_ROOT" "$path"
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -o|--output-dir)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OUTPUT_DIR="$2"
        shift 2
        ;;
      --text)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        WATERMARK_TEXT="$2"
        shift 2
        ;;
      --font)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        FONT_PATH="$2"
        shift 2
        ;;
      --logo)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        LOGO_PATH="$2"
        shift 2
        ;;
      --source-title)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        SOURCE_TITLE="$2"
        shift 2
        ;;
      --mode)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        MODE="$2"
        shift 2
        ;;
      --position)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        POSITION="$2"
        shift 2
        ;;
      --config)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        CONFIG_PATH="$2"
        shift 2
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      --)
        shift
        while [ "$#" -gt 0 ]; do
          VIDEO_IDS+=("$1")
          shift
        done
        ;;
      -*)
        die "Unknown option: $1"
        ;;
      *)
        VIDEO_IDS+=("$1")
        shift
        ;;
    esac
  done
}

resolve_run_dir() {
  local value="$1"
  local candidate

  candidate="$(absolute_path "$value")"
  if [ -d "$candidate" ] && [ -f "$candidate/result.json" ]; then
    printf '%s\n' "$candidate"
    return
  fi

  candidate="$(absolute_path "$OUTPUT_DIR")/$value"
  if [ -d "$candidate" ] && [ -f "$candidate/result.json" ]; then
    printf '%s\n' "$candidate"
    return
  fi

  die "Run directory/result.json not found for: $value"
}

main() {
  parse_args "$@"
  [ "${#VIDEO_IDS[@]}" -gt 0 ] || {
    usage
    die "At least one video id or run directory is required."
  }

  if [ -d "$DEFAULT_FFMPEG_FULL_BIN" ]; then
    export PATH="$DEFAULT_FFMPEG_FULL_BIN:$PATH"
  fi

  mkdir -p "$REPO_ROOT/assets/watermark"

  for video_id in "${VIDEO_IDS[@]}"; do
    run_dir="$(resolve_run_dir "$video_id")"
    result_json="$run_dir/result.json"
    args=("$REPO_ROOT/scripts/watermark_generator.py" "$result_json" "$run_dir")

    [ -n "$CONFIG_PATH" ] && args+=(--config "$(absolute_path "$CONFIG_PATH")")
    [ -n "$WATERMARK_TEXT" ] && args+=(--text "$WATERMARK_TEXT")
    [ -n "$FONT_PATH" ] && args+=(--font "$(absolute_path "$FONT_PATH")")
    [ -n "$LOGO_PATH" ] && args+=(--logo "$(absolute_path "$LOGO_PATH")")
    [ -n "$SOURCE_TITLE" ] && args+=(--source-title "$SOURCE_TITLE")
    [ -n "$MODE" ] && args+=(--mode "$MODE")
    [ -n "$POSITION" ] && args+=(--position "$POSITION")
    [ "$DRY_RUN" = "1" ] && args+=(--dry-run)

    log "Applying watermark: $run_dir"
    python3 "${args[@]}"
    log "[done] watermark - $run_dir/watermarked"
  done
}

main "$@"
