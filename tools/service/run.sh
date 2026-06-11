#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

OUTPUT_DIR="storage/free-viral-shorts"
NUM_CLIPS=""
QUALITY=""
LANGUAGES=""
ASPECT_RATIO=""
MIN_DURATION=""
MAX_DURATION=""
CROP_START=""
CROP_END=""
SKIP_DOWNLOAD=0
SKIP_TRANSCRIPT=0
SKIP_RENDER=0
ANALYZE_ONLY=0
OPENING_STATEMENT=""
OPENING_IMAGE=""
OPENING_VOICE=""
OPENING_RATE=""
OPENING_PITCH=""
OPENING_THUMBNAIL_TITLE=""
OPENING_THUMBNAIL_TALENTS=""
OPENING_THUMBNAIL_FONT=""
OPENING_UPLOAD_TITLE=""
OPENING_SOURCE_TITLE=""
OPENING_BGM=""
OPENING_BGM_VOLUME=""
OPENING_REVIEW_GATE=0
OPENING_BGM_REVIEW_GATE=0
TRANSCRIPT_REVIEW_GATE=0
SUBTITLE_FONT_NAME=""
WHISPER_MODEL="${WHISPER_MODEL:-small}"
WHISPER_PRESET="${WHISPER_PRESET:-fast}"

WATERMARK_ENABLED=1
WATERMARK_TEXT=""
WATERMARK_FONT=""
WATERMARK_LOGO=""
WATERMARK_MODE=""
WATERMARK_POSITION=""
WATERMARK_CONFIG=""
WATERMARK_DRY_RUN=0
WATERMARK_REVIEW_GATE=0

SOURCES=()

log() {
  printf '[run] %s\n' "$*" >&2
}

die() {
  printf '[run] ERROR: %s\n' "$*" >&2
  exit 1
}

write_loading_state() {
  local run_dir="$1"
  local video_id="$2"
  local state="$3"
  local step="$4"
  local total="$5"
  local label="$6"
  local detail="${7:-}"
  local progress

  progress="$(python3 - "$step" "$total" <<'PY'
import sys
step = int(sys.argv[1])
total = max(1, int(sys.argv[2]))
print(round(max(0, min(100, step / total * 100)), 2))
PY
)"

  mkdir -p "$run_dir"
  python3 - "$run_dir" "$video_id" "$state" "$step" "$total" "$progress" "$label" "$detail" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

run_dir = Path(sys.argv[1])
payload = {
    "video_id": sys.argv[2],
    "state": sys.argv[3],
    "step": int(sys.argv[4]),
    "total_steps": int(sys.argv[5]),
    "progress": float(sys.argv[6]),
    "label": sys.argv[7],
    "detail": sys.argv[8],
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
(run_dir / "loading_state.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
with (run_dir / "loading_history.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
PY
  log "[$step/$total] ${label}${detail:+ - $detail}"
}

prepare_watermark_review_gate() {
  local run_dir="$1"
  local review_json="$run_dir/watermark_review.json"
  local decision_json="$run_dir/watermark_review_decision.json"

  [ "$WATERMARK_REVIEW_GATE" = "1" ] || return
  rm -f "$decision_json"
  python3 - "$review_json" "$WATERMARK_TEXT" "$WATERMARK_FONT" "$WATERMARK_LOGO" "$WATERMARK_MODE" "$WATERMARK_POSITION" "$OPENING_SOURCE_TITLE" <<'PY'
import json
import sys
from pathlib import Path

review_json, text, font, logo, mode, position, source_title = sys.argv[1:8]
payload = {
    "status": "waiting_for_user",
    "watermark_text": text,
    "font_path": font,
    "logo_path": logo,
    "mode": mode or "text",
    "position": position or "center_15_top",
    "source_title": source_title,
}
Path(review_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

  log "Watermark review ready: $review_json"
  while [ ! -f "$decision_json" ]; do
    sleep 1
  done

  local decision_env
  decision_env="$run_dir/watermark_review_decision.env"
  python3 - "$decision_json" > "$decision_env" <<'PY'
import json
import shlex
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
mapping = {
    "WATERMARK_TEXT": payload.get("watermark_text", ""),
    "WATERMARK_FONT": payload.get("font_path", ""),
    "WATERMARK_LOGO": payload.get("logo_path", ""),
    "WATERMARK_MODE": payload.get("mode", ""),
    "WATERMARK_POSITION": payload.get("position", ""),
    "OPENING_SOURCE_TITLE": payload.get("source_title", ""),
}
for key, value in mapping.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
  # shellcheck disable=SC1090
  . "$decision_env"
  rm -f "$review_json" "$decision_json" "$decision_env"
  log "Watermark review decision applied"
}

usage() {
  cat <<EOF
Usage:
  ./${SCRIPT_NAME} [options] <youtube-url-or-video-id> [more-sources...]

Runs the full short pipeline:
  1. Download/reuse YouTube video
  2. Extract/reuse transcript
  3. Find viral moments
  4. Analyze visual layout
  5. Generate ASS subtitles
  6. Render shorts
  7. Apply watermark

Pipeline options:
  -n, --num-clips N          Number of shorts
  -o, --output-dir DIR       Output folder. Default: ${OUTPUT_DIR}
  -q, --quality HEIGHT       Download quality cap
  -l, --languages LIST       Transcript language priority
  --aspect-ratio RATIO       9:16 short, 16:9 crop, or 1:1
  --min-duration SEC         Minimum moment duration
  --max-duration SEC         Maximum moment duration
  --crop-start SEC           Source timeline crop start
  --crop-end SEC             Source timeline crop end
  --skip-download            Reuse existing source video
  --skip-transcript          Reuse existing transcript
  --skip-render              Stop before rendering MP4 shorts
  --analyze-only             Same as --skip-download --skip-render
  --opening-statement TEXT   Prepend Edge-TTS opening narration to each short
  --opening-image FILE       Optional image used as the opening narration visual
  --opening-thumbnail-title TEXT
                             Manual thumbnail title used to auto-generate opening visual from the short
  --opening-thumbnail-talents LIST
                             Comma-separated manual talent names for thumbnail labels
  --opening-thumbnail-font FILE
                             TTF/OTF font path for opening thumbnail title
  --opening-upload-title TEXT
                             Upload title used as thumbnail title fallback
  --opening-source-title TEXT
                             Source label shown at top-left of thumbnail
  --opening-bgm FILE          Optional background music mixed under opening narration
  --opening-bgm-volume N      Opening BGM volume
  --opening-review-gate       Pause before opening narration for dashboard review
  --opening-bgm-review-gate   Pause before opening narration for BGM review
  --transcript-review-gate    Pause after transcript extraction for dashboard review
  --opening-voice VOICE      Edge-TTS voice
  --opening-rate RATE        Edge-TTS rate, for example +10%
  --opening-pitch PITCH      Edge-TTS pitch, for example +0Hz
  --subtitle-font-name NAME  ASS subtitle font family name

Watermark options:
  --no-watermark             Do not apply watermark after render
  --watermark-text TEXT      Watermark text
  --watermark-font FILE      Watermark font file
  --watermark-logo FILE      Watermark logo file
  --watermark-mode MODE      text, logo, auto, safe_badge, split_safe
  --watermark-position POS   center_15_top, center, top_right, etc.
  --watermark-config FILE    Watermark config JSON
  --watermark-dry-run        Build watermark plan only
  --watermark-review-gate    Pause before watermark apply for dashboard review

Examples:
  ./${SCRIPT_NAME} -n 3 "https://youtu.be/VIDEO_ID"
  ./${SCRIPT_NAME} --skip-download --skip-transcript -n 1 VIDEO_ID
  ./${SCRIPT_NAME} --max-duration 55 --watermark-text "@KilasanVideo" VIDEO_ID
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

video_id_from() {
  python3 - "$1" <<'PY'
import re
import sys
from urllib.parse import parse_qs, urlparse

value = sys.argv[1].strip()
if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
    print(value)
    raise SystemExit

parsed = urlparse(value)
host = parsed.netloc.lower().replace("www.", "")
parts = [part for part in parsed.path.split("/") if part]

if host == "youtu.be" and parts:
    print(parts[0][:11])
    raise SystemExit

query_id = parse_qs(parsed.query).get("v", [None])[0]
if query_id:
    print(query_id[:11])
    raise SystemExit

if host.endswith("youtube.com") and parts and parts[0] in {"shorts", "embed", "live"} and len(parts) > 1:
    print(parts[1][:11])
    raise SystemExit

match = re.search(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", value)
if match:
    print(match.group(1))
    raise SystemExit

raise SystemExit(f"Cannot extract YouTube video id from: {value}")
PY
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -n|--num-clips)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        NUM_CLIPS="$2"
        shift 2
        ;;
      -o|--output-dir)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OUTPUT_DIR="$2"
        shift 2
        ;;
      -q|--quality)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        QUALITY="$2"
        shift 2
        ;;
      -l|--languages|--language)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        LANGUAGES="$2"
        shift 2
        ;;
      --aspect-ratio)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        ASPECT_RATIO="$2"
        shift 2
        ;;
      --min-duration)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        MIN_DURATION="$2"
        shift 2
        ;;
      --max-duration)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        MAX_DURATION="$2"
        shift 2
        ;;
      --crop-start)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        CROP_START="$2"
        shift 2
        ;;
      --crop-end)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        CROP_END="$2"
        shift 2
        ;;
      --skip-download)
        SKIP_DOWNLOAD=1
        shift
        ;;
      --skip-transcript)
        SKIP_TRANSCRIPT=1
        shift
        ;;
      --skip-render)
        SKIP_RENDER=1
        shift
        ;;
      --opening-statement)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_STATEMENT="$2"
        shift 2
        ;;
      --opening-image)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_IMAGE="$2"
        shift 2
        ;;
      --opening-thumbnail-title)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_THUMBNAIL_TITLE="$2"
        shift 2
        ;;
      --opening-thumbnail-talents)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_THUMBNAIL_TALENTS="$2"
        shift 2
        ;;
      --opening-thumbnail-font)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_THUMBNAIL_FONT="$2"
        shift 2
        ;;
      --opening-upload-title)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_UPLOAD_TITLE="$2"
        shift 2
        ;;
      --opening-source-title)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_SOURCE_TITLE="$2"
        shift 2
        ;;
      --opening-bgm)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_BGM="$2"
        shift 2
        ;;
      --opening-bgm-volume)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_BGM_VOLUME="$2"
        shift 2
        ;;
      --opening-review-gate)
        OPENING_REVIEW_GATE=1
        shift
        ;;
      --transcript-review-gate)
        TRANSCRIPT_REVIEW_GATE=1
        shift
        ;;
      --opening-bgm-review-gate)
        OPENING_BGM_REVIEW_GATE=1
        shift
        ;;
      --opening-voice)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_VOICE="$2"
        shift 2
        ;;
      --opening-rate)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_RATE="$2"
        shift 2
        ;;
      --opening-pitch)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OPENING_PITCH="$2"
        shift 2
        ;;
      --subtitle-font-name)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        SUBTITLE_FONT_NAME="$2"
        shift 2
        ;;
      --whisper-model)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        WHISPER_MODEL="$2"
        shift 2
        ;;
      --whisper-preset)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        WHISPER_PRESET="$2"
        shift 2
        ;;
      --analyze-only)
        ANALYZE_ONLY=1
        SKIP_DOWNLOAD=1
        SKIP_RENDER=1
        shift
        ;;
      --no-watermark)
        WATERMARK_ENABLED=0
        shift
        ;;
      --watermark-text)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        WATERMARK_TEXT="$2"
        shift 2
        ;;
      --watermark-font)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        WATERMARK_FONT="$2"
        shift 2
        ;;
      --watermark-logo)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        WATERMARK_LOGO="$2"
        shift 2
        ;;
      --watermark-mode)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        WATERMARK_MODE="$2"
        shift 2
        ;;
      --watermark-position)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        WATERMARK_POSITION="$2"
        shift 2
        ;;
      --watermark-config)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        WATERMARK_CONFIG="$2"
        shift 2
        ;;
      --watermark-dry-run)
        WATERMARK_DRY_RUN=1
        shift
        ;;
      --watermark-review-gate)
        WATERMARK_REVIEW_GATE=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      --)
        shift
        while [ "$#" -gt 0 ]; do
          SOURCES+=("$1")
          shift
        done
        ;;
      -*)
        die "Unknown option: $1"
        ;;
      *)
        SOURCES+=("$1")
        shift
        ;;
    esac
  done
}

main() {
  parse_args "$@"

  [ "${#SOURCES[@]}" -gt 0 ] || {
    usage
    die "At least one YouTube URL or video ID is required."
  }

  local viral_args=()
  [ -n "$NUM_CLIPS" ] && viral_args+=("-n" "$NUM_CLIPS")
  [ -n "$OUTPUT_DIR" ] && viral_args+=("-o" "$OUTPUT_DIR")
  [ -n "$QUALITY" ] && viral_args+=("-q" "$QUALITY")
  [ -n "$LANGUAGES" ] && viral_args+=("-l" "$LANGUAGES")
  [ -n "$ASPECT_RATIO" ] && viral_args+=("--aspect-ratio" "$ASPECT_RATIO")
  [ -n "$MIN_DURATION" ] && viral_args+=("--min-duration" "$MIN_DURATION")
  [ -n "$MAX_DURATION" ] && viral_args+=("--max-duration" "$MAX_DURATION")
  [ -n "$CROP_START" ] && viral_args+=("--crop-start" "$CROP_START")
  [ -n "$CROP_END" ] && viral_args+=("--crop-end" "$CROP_END")
  [ "$SKIP_DOWNLOAD" = "1" ] && viral_args+=("--skip-download")
  [ "$SKIP_TRANSCRIPT" = "1" ] && viral_args+=("--skip-transcript")
  [ "$SKIP_RENDER" = "1" ] && viral_args+=("--skip-render")
  [ "$ANALYZE_ONLY" = "1" ] && viral_args+=("--analyze-only")
  [ -n "$OPENING_STATEMENT" ] && viral_args+=("--opening-statement" "$OPENING_STATEMENT")
  [ -n "$OPENING_IMAGE" ] && viral_args+=("--opening-image" "$OPENING_IMAGE")
  [ -n "$OPENING_THUMBNAIL_TITLE" ] && viral_args+=("--opening-thumbnail-title" "$OPENING_THUMBNAIL_TITLE")
  [ -n "$OPENING_THUMBNAIL_TALENTS" ] && viral_args+=("--opening-thumbnail-talents" "$OPENING_THUMBNAIL_TALENTS")
  [ -n "$OPENING_THUMBNAIL_FONT" ] && viral_args+=("--opening-thumbnail-font" "$OPENING_THUMBNAIL_FONT")
  [ -n "$OPENING_UPLOAD_TITLE" ] && viral_args+=("--opening-upload-title" "$OPENING_UPLOAD_TITLE")
  [ -n "$OPENING_SOURCE_TITLE" ] && viral_args+=("--opening-source-title" "$OPENING_SOURCE_TITLE")
  [ -n "$OPENING_BGM" ] && viral_args+=("--opening-bgm" "$OPENING_BGM")
  [ -n "$OPENING_BGM_VOLUME" ] && viral_args+=("--opening-bgm-volume" "$OPENING_BGM_VOLUME")
  [ "$OPENING_REVIEW_GATE" = "1" ] && viral_args+=("--opening-review-gate")
  [ "$OPENING_BGM_REVIEW_GATE" = "1" ] && viral_args+=("--opening-bgm-review-gate")
  [ "$TRANSCRIPT_REVIEW_GATE" = "1" ] && viral_args+=("--transcript-review-gate")
  [ -n "$OPENING_VOICE" ] && viral_args+=("--opening-voice" "$OPENING_VOICE")
  [ -n "$OPENING_RATE" ] && viral_args+=("--opening-rate" "$OPENING_RATE")
  [ -n "$OPENING_PITCH" ] && viral_args+=("--opening-pitch" "$OPENING_PITCH")
  [ -n "$SUBTITLE_FONT_NAME" ] && viral_args+=("--subtitle-font-name" "$SUBTITLE_FONT_NAME")
  [ -n "$WHISPER_MODEL" ] && viral_args+=("--whisper-model" "$WHISPER_MODEL")
  [ -n "$WHISPER_PRESET" ] && viral_args+=("--whisper-preset" "$WHISPER_PRESET")
  viral_args+=("${SOURCES[@]}")

  log "Running viral shorts pipeline"
  if [ "$WATERMARK_ENABLED" = "1" ] && [ "$SKIP_RENDER" != "1" ]; then
    DEFER_COMPLETED_STATE=1 "$REPO_ROOT/tools/media/free_viral_shorts.sh" "${viral_args[@]}"
  else
    "$REPO_ROOT/tools/media/free_viral_shorts.sh" "${viral_args[@]}"
  fi

  if [ "$WATERMARK_ENABLED" != "1" ]; then
    log "Watermark disabled"
    exit 0
  fi

  if [ "$SKIP_RENDER" = "1" ]; then
    log "Skipping watermark because render was skipped"
    exit 0
  fi

  local total_steps=13
  local source
  for source in "${SOURCES[@]}"; do
    local video_id run_dir
    video_id="$(video_id_from "$source")"
    run_dir="$(absolute_path "$OUTPUT_DIR")/$video_id"
    if [ "$WATERMARK_REVIEW_GATE" = "1" ]; then
      write_loading_state "$run_dir" "$video_id" "waiting" 10 "$total_steps" "Watermark review" "Review watermark text, font, mode, position, and source title"
      prepare_watermark_review_gate "$run_dir"
    fi
    write_loading_state "$run_dir" "$video_id" "running" 11 "$total_steps" "Applying watermark" "Rendering watermarked final output"
  done

  local watermark_args=("-o" "$OUTPUT_DIR")
  [ -n "$WATERMARK_TEXT" ] && watermark_args+=("--text" "$WATERMARK_TEXT")
  [ -n "$WATERMARK_FONT" ] && watermark_args+=("--font" "$WATERMARK_FONT")
  [ -n "$WATERMARK_LOGO" ] && watermark_args+=("--logo" "$WATERMARK_LOGO")
  [ -n "$OPENING_SOURCE_TITLE" ] && watermark_args+=("--source-title" "$OPENING_SOURCE_TITLE")
  [ -n "$WATERMARK_MODE" ] && watermark_args+=("--mode" "$WATERMARK_MODE")
  [ -n "$WATERMARK_POSITION" ] && watermark_args+=("--position" "$WATERMARK_POSITION")
  [ -n "$WATERMARK_CONFIG" ] && watermark_args+=("--config" "$WATERMARK_CONFIG")
  [ "$WATERMARK_DRY_RUN" = "1" ] && watermark_args+=("--dry-run")

  for source in "${SOURCES[@]}"; do
    watermark_args+=("$(video_id_from "$source")")
  done

  log "Applying watermark to rendered shorts"
  "$REPO_ROOT/tools/media/watermark_shorts.sh" "${watermark_args[@]}"
  for source in "${SOURCES[@]}"; do
    local video_id run_dir
    video_id="$(video_id_from "$source")"
    run_dir="$(absolute_path "$OUTPUT_DIR")/$video_id"
    write_loading_state "$run_dir" "$video_id" "completed" 13 "$total_steps" "Completed" "Final artifacts are ready"
  done
  log "Done. Final videos are in $(absolute_path "$OUTPUT_DIR")/<video-id>/watermarked"
}

main "$@"
