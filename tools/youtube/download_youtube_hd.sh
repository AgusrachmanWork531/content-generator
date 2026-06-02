#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"
DEFAULT_OUTPUT_DIR="storage/video"
DEFAULT_HEIGHT="1080"
DEFAULT_RETRIES="10"
DEFAULT_FRAGMENT_RETRIES="10"
DEFAULT_CONCURRENT_FRAGMENTS="4"

OUTPUT_DIR="${OUTPUT_DIR:-$DEFAULT_OUTPUT_DIR}"
HEIGHT="${HEIGHT:-$DEFAULT_HEIGHT}"
RETRIES="${RETRIES:-$DEFAULT_RETRIES}"
FRAGMENT_RETRIES="${FRAGMENT_RETRIES:-$DEFAULT_FRAGMENT_RETRIES}"
CONCURRENT_FRAGMENTS="${CONCURRENT_FRAGMENTS:-$DEFAULT_CONCURRENT_FRAGMENTS}"
COOKIES_FILE=""
COOKIES_BROWSER=""
WRITE_SUBS=0
KEEP_PARTS=1
DRY_RUN=0
URLS=()

log() {
  printf '[youtube-hd] %s\n' "$*" >&2
}

die() {
  printf '[youtube-hd] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage:
  ./${SCRIPT_NAME} [options] <youtube-url> [youtube-url...]

Options:
  -o, --output-dir DIR       Output folder. Default: ${DEFAULT_OUTPUT_DIR}
  -q, --quality HEIGHT       Max video height: 720, 1080, 1440, 2160, or best.
                             Default: ${DEFAULT_HEIGHT}
  --cookies FILE             Use a cookies.txt file for age/private/member videos.
  --cookies-from-browser B   Read cookies from browser: chrome, safari, firefox, etc.
  --subs                     Download available subtitles as sidecar files.
  --retries N                Whole-download retries. Default: ${DEFAULT_RETRIES}
  --fragment-retries N       Fragment retries. Default: ${DEFAULT_FRAGMENT_RETRIES}
  --fragments N              Concurrent fragments. Default: ${DEFAULT_CONCURRENT_FRAGMENTS}
  --no-keep-parts            Remove partial files if download fails.
  --dry-run                  Print what would be downloaded without downloading.
  -h, --help                 Show this help.

Examples:
  ./${SCRIPT_NAME} "https://youtu.be/VIDEO_ID"
  ./${SCRIPT_NAME} -q 2160 -o storage/video "https://youtube.com/watch?v=VIDEO_ID"
  ./${SCRIPT_NAME} --cookies-from-browser chrome "https://youtube.com/watch?v=VIDEO_ID"

Dependencies:
  yt-dlp and ffmpeg must be installed.
  macOS: brew install yt-dlp ffmpeg
EOF
}

cleanup_on_error() {
  local exit_code=$?
  if [ "$exit_code" -ne 0 ] && [ "$KEEP_PARTS" = "0" ]; then
    find "$OUTPUT_DIR" -type f \( -name '*.part' -o -name '*.ytdl' -o -name '*.temp.*' \) -delete 2>/dev/null || true
  fi
  exit "$exit_code"
}
trap cleanup_on_error EXIT

require_command() {
  local command_name="$1"
  local install_hint="$2"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    die "'${command_name}' not found. ${install_hint}"
  fi
}

is_positive_int() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *) [ "$1" -gt 0 ] ;;
  esac
}

validate_height() {
  case "$HEIGHT" in
    best|240|360|480|720|1080|1440|2160|4320) ;;
    *)
      die "Invalid quality '${HEIGHT}'. Use 720, 1080, 1440, 2160, 4320, or best."
      ;;
  esac
}

build_format_selector() {
  if [ "$HEIGHT" = "best" ]; then
    printf '%s' 'bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b'
    return
  fi

  printf '%s' "bv*[height<=${HEIGHT}][ext=mp4]+ba[ext=m4a]/bv*[height<=${HEIGHT}]+ba/b[height<=${HEIGHT}][ext=mp4]/b[height<=${HEIGHT}]"
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -o|--output-dir)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OUTPUT_DIR="$2"
        shift 2
        ;;
      -q|--quality)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        HEIGHT="$2"
        shift 2
        ;;
      --cookies)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        COOKIES_FILE="$2"
        shift 2
        ;;
      --cookies-from-browser)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        COOKIES_BROWSER="$2"
        shift 2
        ;;
      --subs)
        WRITE_SUBS=1
        shift
        ;;
      --retries)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        RETRIES="$2"
        shift 2
        ;;
      --fragment-retries)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        FRAGMENT_RETRIES="$2"
        shift 2
        ;;
      --fragments)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        CONCURRENT_FRAGMENTS="$2"
        shift 2
        ;;
      --no-keep-parts)
        KEEP_PARTS=0
        shift
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
          URLS+=("$1")
          shift
        done
        ;;
      -*)
        die "Unknown option: $1"
        ;;
      *)
        URLS+=("$1")
        shift
        ;;
    esac
  done
}

main() {
  parse_args "$@"

  [ "${#URLS[@]}" -gt 0 ] || {
    usage
    die "At least one YouTube URL is required."
  }

  validate_height
  is_positive_int "$RETRIES" || die "--retries must be a positive integer."
  is_positive_int "$FRAGMENT_RETRIES" || die "--fragment-retries must be a positive integer."
  is_positive_int "$CONCURRENT_FRAGMENTS" || die "--fragments must be a positive integer."
  [ -z "$COOKIES_FILE" ] || [ -f "$COOKIES_FILE" ] || die "Cookies file not found: $COOKIES_FILE"

  require_command "yt-dlp" "Install it with: brew install yt-dlp"
  require_command "ffmpeg" "Install it with: brew install ffmpeg"

  mkdir -p "$OUTPUT_DIR"

  local format_selector
  format_selector="$(build_format_selector)"

  local args=(
    --format "$format_selector"
    --merge-output-format mp4
    --remux-video mp4
    --continue
    --no-overwrites
    --ignore-errors
    --no-abort-on-error
    --retries "$RETRIES"
    --fragment-retries "$FRAGMENT_RETRIES"
    --retry-sleep "fragment:exp=1:20"
    --retry-sleep "http:exp=1:30"
    --socket-timeout 30
    --concurrent-fragments "$CONCURRENT_FRAGMENTS"
    --force-ipv4
    --restrict-filenames
    --trim-filenames 180
    --windows-filenames
    --paths "$OUTPUT_DIR"
    --output "%(upload_date>%Y-%m-%d|unknown)s_%(title).180B_%(id)s.%(ext)s"
    --download-archive "${OUTPUT_DIR}/.downloaded-archive.txt"
    --no-mtime
    --progress
  )

  if [ "$DRY_RUN" = "1" ]; then
    args+=(--simulate --print "%(title)s | %(resolution)s | %(duration_string)s | %(webpage_url)s")
  fi

  if [ "$WRITE_SUBS" = "1" ]; then
    args+=(--write-subs --write-auto-subs --sub-langs "id,en.*" --convert-subs srt)
  fi

  if [ -n "$COOKIES_FILE" ]; then
    args+=(--cookies "$COOKIES_FILE")
  fi

  if [ -n "$COOKIES_BROWSER" ]; then
    args+=(--cookies-from-browser "$COOKIES_BROWSER")
  fi

  log "Output dir: $OUTPUT_DIR"
  log "Quality cap: $HEIGHT"
  log "URLs: ${#URLS[@]}"

  yt-dlp "${args[@]}" "${URLS[@]}"

  log "Done."
}

main "$@"
