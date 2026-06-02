#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEFAULT_OUTPUT_DIR="storage/free-viral-shorts"
DEFAULT_TRANSCRIPT_DIR="storage/transcripts"
DEFAULT_VIDEO_DIR="storage/video"
DEFAULT_NUM_CLIPS="3"
DEFAULT_QUALITY="1080"
DEFAULT_LANGUAGES="id,en"
DEFAULT_ASPECT_RATIO="9:16"
DEFAULT_MIN_DURATION="45"
DEFAULT_MAX_DURATION="55"
DEFAULT_SMART_CROP_ENGINE="pyautoflip"
DEFAULT_PYAUTOFLIP_METHOD="detection"
DEFAULT_PYAUTOFLIP_PADDING="blur"

# Subtitle pipeline config
# NOTE: Using fast transcript-based timing instead of slow WhisperX full-video transcription
# Set to 1 only if you need exact WhisperX word timestamps (slower, ~10min for 50min video)

OUTPUT_DIR="${OUTPUT_DIR:-$DEFAULT_OUTPUT_DIR}"
TRANSCRIPT_DIR="${TRANSCRIPT_DIR:-$DEFAULT_TRANSCRIPT_DIR}"
VIDEO_DIR="${VIDEO_DIR:-$DEFAULT_VIDEO_DIR}"
NUM_CLIPS="${NUM_CLIPS:-$DEFAULT_NUM_CLIPS}"
QUALITY="${QUALITY:-$DEFAULT_QUALITY}"
LANGUAGES="${LANGUAGES:-$DEFAULT_LANGUAGES}"
ASPECT_RATIO="${ASPECT_RATIO:-$DEFAULT_ASPECT_RATIO}"
MIN_DURATION="${MIN_DURATION:-$DEFAULT_MIN_DURATION}"
MAX_DURATION="${MAX_DURATION:-$DEFAULT_MAX_DURATION}"
SMART_CROP_ENGINE="${SMART_CROP_ENGINE:-$DEFAULT_SMART_CROP_ENGINE}"
PYAUTOFLIP_METHOD="${PYAUTOFLIP_METHOD:-$DEFAULT_PYAUTOFLIP_METHOD}"
PYAUTOFLIP_PADDING="${PYAUTOFLIP_PADDING:-$DEFAULT_PYAUTOFLIP_PADDING}"
CROP_START="${CROP_START:-}"
CROP_END="${CROP_END:-}"
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
SOURCES=()

log() {
  printf '[free-viral-shorts] %s\n' "$*" >&2
}

die() {
  printf '[free-viral-shorts] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
  ./${SCRIPT_NAME} [options] <youtube-url-or-video-id> [more-sources...]

Options:
  -n, --num-clips N          Number of shorts. Default: ${DEFAULT_NUM_CLIPS}
  -o, --output-dir DIR       Output folder. Default: ${DEFAULT_OUTPUT_DIR}
  -q, --quality HEIGHT       Download quality cap. Default: ${DEFAULT_QUALITY}
  -l, --languages LIST       Transcript language priority. Default: ${DEFAULT_LANGUAGES}
  --aspect-ratio RATIO       Output ratio. Default: ${DEFAULT_ASPECT_RATIO}
  --min-duration SEC         Kept for compatibility; entertainment candidates stay 45-55s.
  --max-duration SEC         Kept for compatibility; entertainment candidates stay 45-55s.
  --crop-start SEC           Direct crop start.
  --crop-end SEC             Direct crop end.
  --skip-download            Reuse existing source video.
  --skip-transcript          Reuse existing transcript.
  --skip-render              Stop before rendering MP4 shorts.
  --analyze-only             Same as --skip-download --skip-render.
  -h, --help                 Show this help.
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


source_url_for() {
  local source="$1"
  local video_id="$2"
  if [[ "$source" =~ ^https?:// ]]; then
    printf '%s\n' "$source"
  else
    printf 'https://youtu.be/%s\n' "$video_id"
  fi
}


is_positive_int() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *) [ "$1" -gt 0 ] ;;
  esac
}


choose_ffmpeg() {
  local candidate
  local candidates=()

  if [ -n "${FFMPEG_BIN:-}" ] && [ -x "${FFMPEG_BIN:-}" ]; then
    candidates+=("$FFMPEG_BIN")
  fi
  if [ -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ]; then
    candidates+=("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
  fi
  if [ -x /opt/homebrew/bin/ffmpeg ]; then
    candidates+=("/opt/homebrew/bin/ffmpeg")
  fi
  if command -v ffmpeg >/dev/null 2>&1; then
    candidates+=("$(command -v ffmpeg)")
  fi

  for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

ffmpeg_has_subtitles_filter() {
  local ffmpeg_bin="$1"
  "$ffmpeg_bin" -hide_banner -filters 2>/dev/null | grep -qE ' subtitles '
}



choose_cv_python() {
  if [ -n "${CV_PYTHON_BIN:-}" ] && [ -x "${CV_PYTHON_BIN:-}" ]; then
    printf '%s\n' "$CV_PYTHON_BIN"
    return
  fi
  if [ -x "$REPO_ROOT/.venv-api/bin/python" ]; then
    printf '%s\n' "$REPO_ROOT/.venv-api/bin/python"
    return
  fi
  command -v python3 || true
}


write_loading_state() {
  local run_dir="$1"
  local video_id="$2"
  local state="$3"
  local step="$4"
  local total="$5"
  local label="$6"
  local detail="${7:-}"

  mkdir -p "$run_dir"
  python3 - "$run_dir" "$video_id" "$state" "$step" "$total" "$label" "$detail" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

run_dir = Path(sys.argv[1])
step = int(sys.argv[4])
total = max(1, int(sys.argv[5]))
payload = {
    "video_id": sys.argv[2],
    "state": sys.argv[3],
    "step": step,
    "total_steps": total,
    "progress": round(max(0, min(100, step / total * 100)), 2),
    "label": sys.argv[6],
    "detail": sys.argv[7],
    "updated_at": datetime.now(timezone.utc).isoformat(),
}

(run_dir / "loading_state.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
with (run_dir / "loading_history.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
PY
  log "[$step/$total] ${label}${detail:+ - $detail}"
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
      --analyze-only)
        ANALYZE_ONLY=1
        SKIP_DOWNLOAD=1
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
      --opening-review-gate|--opening-bgm-review-gate|--transcript-review-gate)
        shift
        ;;
      --opening-voice|--opening-rate|--opening-pitch|--subtitle-font-name)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        shift 2
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


find_video_file() {
  local video_id="$1"
  python3 - "$(absolute_path "$VIDEO_DIR")" "$video_id" <<'PY'
import sys
from pathlib import Path

video_dir = Path(sys.argv[1])
video_id = sys.argv[2]
extensions = {".mp4", ".mkv", ".webm", ".mov"}
if not video_dir.exists():
    raise SystemExit(0)
matches = [
    path for path in video_dir.iterdir()
    if path.is_file() and video_id in path.name and path.suffix.lower() in extensions
]
matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
if matches:
    print(matches[0])
PY
}


ensure_transcript() {
  local source_url="$1"
  local video_id="$2"
  local abs_transcript_dir
  abs_transcript_dir="$(absolute_path "$TRANSCRIPT_DIR")"

  if [ "$SKIP_TRANSCRIPT" = "0" ] && [ ! -f "$abs_transcript_dir/$video_id/transcript.clean.json" ]; then
    log "Extracting YouTube transcript"
    "$REPO_ROOT/tools/youtube/transcribe_youtube.sh" -o "$abs_transcript_dir" -l "$LANGUAGES" "$source_url"
  fi

  [ -f "$abs_transcript_dir/$video_id/transcript.clean.json" ] ||
    die "Transcript not found: $abs_transcript_dir/$video_id/transcript.clean.json"
}


ensure_video() {
  local source_url="$1"
  local video_id="$2"
  local video_file

  video_file="$(find_video_file "$video_id" || true)"
  if [ "$SKIP_DOWNLOAD" = "0" ] && [ -z "$video_file" ]; then
    log "Downloading source video"
    "$REPO_ROOT/tools/youtube/download_youtube_hd.sh" -q "$QUALITY" -o "$(absolute_path "$VIDEO_DIR")" "$source_url" >&2
    video_file="$(find_video_file "$video_id" || true)"
  fi

  if [ "$SKIP_RENDER" = "0" ]; then
    [ -n "$video_file" ] || die "Video not found for rendering. Expected file containing video id: $video_id"
  fi

  printf '%s\n' "$video_file"
}


analyze_moments() {
  local video_id="$1"
  local source_url="$2"
  local transcript_json="$3"
  local run_dir="$4"

  python3 - "$video_id" "$source_url" "$transcript_json" "$run_dir" "$NUM_CLIPS" "$MIN_DURATION" "$MAX_DURATION" "$ASPECT_RATIO" "${CROP_START:-}" "${CROP_END:-}" <<'PY'
import json
import re
import sys
from pathlib import Path

video_id, source_url, transcript_path, run_dir, num_clips, min_duration, max_duration, aspect_ratio, crop_start_raw, crop_end_raw = sys.argv[1:]
num_clips = min(max(1, int(num_clips)), 3)
min_duration = float(min_duration)
max_duration = float(max_duration)
crop_start = float(crop_start_raw) if crop_start_raw else None
crop_end = float(crop_end_raw) if crop_end_raw else None
run_dir = Path(run_dir)
clips_dir = run_dir / "clips"
clips_dir.mkdir(parents=True, exist_ok=True)

segments = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
segments = [s for s in segments if s.get("text") and float(s.get("end", 0)) > float(s.get("start", 0))]

ENTERTAINMENT_MIN_DURATION = 45.0
ENTERTAINMENT_MAX_DURATION = 55.0

CONFIG = {
    "duration_sweet_spot": [45, 55],
    "long_video_threshold_seconds": 1800,
    "chunk_size_seconds": 1200,
    "chunk_overlap_seconds": 60,
    "dedupe_overlap_ratio": 0.50,
    "candidate_durations": [45, 50, 55],
    "candidate_stride_segments": 4,
    # Early exit config: stop after enough high-quality candidates found
    "early_exit_min_score": 50,  # Minimum score to consider as "high quality"
    "early_exit_buffer": 3,  # How many extra candidates to collect beyond num_clips
}


LEXICON = {
    "hook_entertainment": [
        "ternyata", "kok", "hah", "lah", "serius", "gila", "anjir", "buset",
        "kenapa", "ngapain", "masa", "emang", "beneran", "jangan", "eh", "loh",
    ],
    "comedy": [
        "haha", "wkwk", "ketawa", "lucu", "kocak", "ngakak", "ngaco", "aneh",
        "buset", "parah", "ngapain", "kok", "lah",
    ],
    "light_conflict": [
        "tapi", "jangan", "bukan", "ngotot", "susah", "ribut", "marah",
        "kenapa", "enggak", "gak", "masa", "kok",
    ],
    "absurd": [
        "aneh", "kok bisa", "ngapain", "lah", "tiba-tiba", "masa", "emang",
        "malah", "random", "enggak jelas", "gak jelas",
    ],
    "reaction": [
        "hah", "loh", "lah", "waduh", "buset", "astaga", "anjir", "gila",
        "wow", "eh",
    ],
    "escalation": [
        "terus", "tiba-tiba", "malah", "jadi", "makin", "akhirnya", "langsung",
    ],
    "payoff": [
        "ternyata", "malah", "bukan", "jadi", "hah", "loh", "buset", "gila",
        "anjir", "ya",
    ],
    "serious": [
        "meninggal", "bunuh", "darah", "korban", "kecelakaan", "perang",
        "bencana", "penyakit", "kriminal",
    ],
    "informative": [
        "tips", "cara", "tutorial", "informasi", "data", "menjelaskan",
        "penjelasan", "berdasarkan", "riset",
    ],
}


def count_terms(text, words):
    lower = text.lower()
    return sum(lower.count(word) for word in words)


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def first_sentence(text):
    ss = sentences(text)
    if ss:
        return ss[0][:220]
    return text.strip()[:220]


def overlap_ratio(a, b):
    start = max(float(a["start_time"]), float(b["start_time"]))
    end = min(float(a["end_time"]), float(b["end_time"]))
    overlap = max(0.0, end - start)
    dur = max(1.0, float(a["end_time"]) - float(a["start_time"]))
    return overlap / dur


def format_srt_time(seconds):
    seconds = max(0.0, float(seconds))
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    if ms == 1000:
        total += 1
        ms = 0
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_clip_srt(path, clip_segments, clip_start, clip_end):
    rows = []
    for seg in sorted(clip_segments, key=lambda item: (float(item["start"]), float(item["end"]))):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        start = max(0.0, float(seg["start"]) - clip_start)
        end = min(clip_end - clip_start, float(seg["end"]) - clip_start)
        if end <= start:
            continue
        rows.append({"start": start, "end": end, "text": text})

    for idx in range(len(rows) - 1):
        next_start = rows[idx + 1]["start"]
        if rows[idx]["end"] > next_start - 0.04:
            rows[idx]["end"] = max(rows[idx]["start"], next_start - 0.04)

    with path.open("w", encoding="utf-8") as handle:
        for index, seg in enumerate([row for row in rows if row["end"] - row["start"] >= 0.16], start=1):
            handle.write(f"{index}\n")
            handle.write(f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}\n")
            handle.write(seg["text"] + "\n\n")


def window_text(window_segments, start_ratio, end_ratio):
    start = float(window_segments[0]["start"])
    end = float(window_segments[-1]["end"])
    clip_dur = end - start
    win_start = start + clip_dur * start_ratio
    win_end = start + clip_dur * end_ratio
    return " ".join(
        str(seg.get("text", "")).strip()
        for seg in window_segments
        if (
            win_start <= float(seg.get("start", 0)) < win_end
            or win_start < float(seg.get("end", 0)) <= win_end
        )
    ).strip()


def window_text_seconds(window_segments, start_seconds, end_seconds):
    clip_start = float(window_segments[0]["start"])
    win_start = clip_start + start_seconds
    win_end = clip_start + end_seconds
    return " ".join(
        str(seg.get("text", "")).strip()
        for seg in window_segments
        if (
            win_start <= float(seg.get("start", 0)) < win_end
            or win_start < float(seg.get("end", 0)) <= win_end
        )
    ).strip()


def short_final_sentence_bonus(text):
    parts = [part.strip() for part in re.split(r"[.!?]\s*|\n+", text.strip()) if part.strip()]
    if not parts:
        parts = [text.strip()]
    last = parts[-1] if parts else ""
    words = re.findall(r"\w+", last)
    return 3 if 1 <= len(words) <= 8 else 0


def score_candidate(window_segments):
    start = float(window_segments[0]["start"])
    end = float(window_segments[-1]["end"])
    dur = end - start
    text = " ".join(s["text"].strip() for s in window_segments)
    words = re.findall(r"\w+", text.lower())
    unique_words = set(words)
    repetition = 1.0 - (len(unique_words) / max(1, len(words)))

    hook_window = window_text_seconds(window_segments, 0, 3)
    early_window = window_text(window_segments, 0.0, 0.35)
    middle_window = window_text(window_segments, 0.35, 0.70)
    end_window = window_text(window_segments, 0.80, 1.0)
    first_10s = window_text_seconds(window_segments, 0, 10)
    hook_sentence = first_sentence(hook_window) if hook_window.strip() else first_sentence(text)

    hook_score = min(20, count_terms(hook_window, LEXICON["hook_entertainment"]) * 4)
    if "?" in hook_window:
        hook_score += 4
    hook_score = min(20, hook_score)

    comedy_potential = min(20, count_terms(text, LEXICON["comedy"]) * 4)
    light_conflict = min(15, count_terms(text, LEXICON["light_conflict"]) * 3)
    absurdity = min(15, count_terms(text, LEXICON["absurd"]) * 3)
    reaction_moment = min(10, count_terms(text, LEXICON["reaction"]) * 2 + min(3, text.count("?") * 2))

    middle_reaction_conflict = (
        count_terms(middle_window, LEXICON["reaction"])
        + count_terms(middle_window, LEXICON["light_conflict"])
    )
    early_reaction_conflict = (
        count_terms(early_window, LEXICON["reaction"])
        + count_terms(early_window, LEXICON["light_conflict"])
    )
    escalation = min(10, count_terms(middle_window, LEXICON["escalation"]) * 3)
    if middle_reaction_conflict > early_reaction_conflict:
        escalation += 3
    elif middle_reaction_conflict >= early_reaction_conflict and middle_reaction_conflict > 0:
        escalation += 1
    escalation = min(10, escalation)

    payoff = min(15, count_terms(end_window, LEXICON["payoff"]) * 3 + short_final_sentence_bonus(end_window))

    standalone = 0
    if len(window_segments) >= 8:
        standalone += 4
    context_words = ["saya", "aku", "gue", "gua", "kita", "kami", "temen", "orang", "rumah", "tempat", "hari", "waktu", "kerja", "sekolah", "pak", "mas"]
    if any(word in first_10s.lower() for word in context_words):
        standalone += 3
    first_words = first_10s.lower().split()[:4] if first_10s else []
    solo_pronouns = ["dia", "itu", "ini", "mereka", "ya", "nah", "eh", "loh"]
    if first_words and not all(w in solo_pronouns for w in first_words):
        standalone += 3
    standalone = min(10, standalone)

    duration_fit = max(0, 10 - abs(dur - 50.0) * 0.15)
    repetition_penalty = min(10, repetition * 15)
    serious_score = count_terms(text, LEXICON["serious"])
    serious_penalty = min(15, serious_score * 5)
    informative_score = count_terms(text, LEXICON["informative"])
    informative_penalty = min(12, informative_score * 4)

    raw = (
        hook_score + comedy_potential + light_conflict + absurdity
        + reaction_moment + escalation + payoff + standalone
        + duration_fit - repetition_penalty - serious_penalty - informative_penalty
    )
    viral_entertainment_score = int(max(0, min(100, round(raw))))
    signals = {
        "hook_score": hook_score,
        "comedy_potential": comedy_potential,
        "light_conflict": light_conflict,
        "absurdity": absurdity,
        "reaction_moment": reaction_moment,
        "escalation": escalation,
        "payoff": payoff,
        "standalone": standalone,
        "duration_fit": round(duration_fit, 2),
        "repetition_penalty": round(repetition_penalty, 2),
        "serious_penalty": round(serious_penalty, 2),
        "informative_penalty": round(informative_penalty, 2),
    }

    reject = False
    reject_reason = ""
    if viral_entertainment_score < 35:
        reject = True
        reject_reason = "low score"
    elif comedy_potential + light_conflict + absurdity + reaction_moment < 15:
        reject = True
        reject_reason = "flat content"
    elif informative_score >= 3 and comedy_potential + light_conflict + reaction_moment < 10:
        reject = True
        reject_reason = "too informative"
    elif serious_score >= 2 and comedy_potential + light_conflict + reaction_moment < 15:
        reject = True
        reject_reason = "too serious"

    reason_parts = []
    if hook_score >= 10:
        reason_parts.append("strong hook")
    if comedy_potential >= 10:
        reason_parts.append("comedy")
    if light_conflict >= 8:
        reason_parts.append("light conflict")
    if absurdity >= 8:
        reason_parts.append("absurdity")
    if reaction_moment >= 5:
        reason_parts.append("reaction")
    if escalation >= 5:
        reason_parts.append("escalation")
    if payoff >= 8:
        reason_parts.append("payoff")
    if not reason_parts:
        reason_parts = ["balanced entertainment"]

    return {
        "title": first_sentence(text).rstrip(".?!")[:90] or "Untitled moment",
        "start_time": round(start, 3),
        "end_time": round(end, 3),
        "duration": round(dur, 3),
        "score": viral_entertainment_score,
        "viral_entertainment_score": viral_entertainment_score,
        "hook_sentence": hook_sentence,
        "virality_reason": "Entertainment: " + ", ".join(reason_parts),
        "signals": signals,
        "reject": reject,
        "reject_reason": reject_reason,
        "text": text,
        "_segments": window_segments,
    }


def candidate_ranges_for_chunk(chunk_segments):
    candidates = []
    for start_idx in range(0, len(chunk_segments), CONFIG["candidate_stride_segments"]):
        start = float(chunk_segments[start_idx]["start"])
        for target_dur in CONFIG["candidate_durations"]:
            end_target = start + float(target_dur)
            end_idx = start_idx
            while end_idx + 1 < len(chunk_segments) and float(chunk_segments[end_idx]["end"]) < end_target:
                end_idx += 1
            window = chunk_segments[start_idx : end_idx + 1]
            if not window:
                continue
            actual_dur = float(window[-1]["end"]) - float(window[0]["start"])
            if ENTERTAINMENT_MIN_DURATION <= actual_dur <= ENTERTAINMENT_MAX_DURATION and len(window) >= 4:
                candidates.append(window)
    return candidates


def chunk_segments():
    duration = max((float(s["end"]) for s in segments), default=0.0)
    if duration < CONFIG["long_video_threshold_seconds"]:
        return [segments]
    chunks = []
    start = 0.0
    while start < duration:
        end = min(duration, start + CONFIG["chunk_size_seconds"])
        chunk = [s for s in segments if float(s["start"]) >= start and float(s["end"]) <= end + CONFIG["chunk_overlap_seconds"]]
        if chunk:
            chunks.append(chunk)
        start += CONFIG["chunk_size_seconds"] - CONFIG["chunk_overlap_seconds"]
    return chunks


duration = max((float(s["end"]) for s in segments), default=0.0)
direct_crop_mode = crop_start is not None and crop_end is not None and crop_end > crop_start
kept = []

if direct_crop_mode and segments:
    clipped_segments = [s for s in segments if float(s["end"]) > crop_start and float(s["start"]) < crop_end]
    text = " ".join(s["text"].strip() for s in clipped_segments)
    item = {
        "title": f"Crop {crop_start:.1f}s - {crop_end:.1f}s",
        "start_time": round(crop_start, 3),
        "end_time": round(crop_end, 3),
        "duration": round(crop_end - crop_start, 3),
        "score": 100,
        "viral_entertainment_score": 100,
        "hook_sentence": first_sentence(window_text_seconds(clipped_segments, 0, 3)) if clipped_segments else first_sentence(text),
        "virality_reason": "Direct crop-window render. Hook search disabled.",
        "signals": {
            "hook_score": 0, "comedy_potential": 0, "light_conflict": 0, "absurdity": 0,
            "reaction_moment": 0, "escalation": 0, "payoff": 0, "standalone": 0,
            "duration_fit": 0, "repetition_penalty": 0, "serious_penalty": 0, "informative_penalty": 0,
        },
        "text": text,
        "_segments": clipped_segments,
    }
    kept = [item]
    all_candidates = [item]
else:
    # Early exit optimization: Generate candidates with early stop when we have enough high-quality candidates
    # This avoids scoring ALL candidates when we only need a few good ones
    chunks = chunk_segments()
    all_candidates = []
    early_exit_target = num_clips + CONFIG.get("early_exit_buffer", 3)
    early_exit_min_score = CONFIG.get("early_exit_min_score", 50)
    high_quality_found = 0
    
    for chunk in chunks:
        for window in candidate_ranges_for_chunk(chunk):
            scored = score_candidate(window)
            all_candidates.append(scored)
            # Check for early exit condition: enough high-quality (score >= min_score) non-rejected candidates
            if not scored.get("reject", False) and scored.get("viral_entertainment_score", 0) >= early_exit_min_score:
                high_quality_found += 1
            # Early exit: stop generating more if we have enough high-quality candidates
            # and we've processed at least enough to have a buffer
            if high_quality_found >= early_exit_target and len(all_candidates) >= early_exit_target * 10:
                break
        if high_quality_found >= early_exit_target and len(all_candidates) >= early_exit_target * 10:
            break
    
    valid_candidates = sorted(
        [candidate for candidate in all_candidates if not candidate.get("reject", False)],
        key=lambda item: item.get("viral_entertainment_score", item["score"]),
        reverse=True,
    )
    for candidate in valid_candidates:
        if any(overlap_ratio(candidate, kept_item) > CONFIG["dedupe_overlap_ratio"] for kept_item in kept):
            continue
        kept.append(candidate)
        if len(kept) >= num_clips:
            break

for idx, item in enumerate(kept, start=1):
    srt_path = clips_dir / f"clip_{idx:02d}.srt"
    write_clip_srt(srt_path, item["_segments"], item["start_time"], item["end_time"])
    item["subtitle_file"] = str(srt_path)
    item["subtitle_timing_mode"] = "crop_trimmed_monotonic_non_overlap"
    item.pop("_segments", None)

result = {
    "mode": "viral-entertainment-heuristic",
    "source": source_url,
    "video_id": video_id,
    "aspect_ratio": aspect_ratio,
    "config": CONFIG | {
        "num_clips": num_clips,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "crop_start": crop_start,
        "crop_end": crop_end,
    },
    "duration": duration,
    "candidate_count": len(all_candidates),
    "highlights": kept,
    "shorts": [],
}

(run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

lines = [
    "# Viral Entertainment Moments",
    "",
    f"- Source: `{source_url}`",
    f"- Video ID: `{video_id}`",
    f"- Candidates scored: `{len(all_candidates)}`",
    "- Mode: `viral-entertainment-heuristic`",
    "",
]
for idx, item in enumerate(kept, start=1):
    sigs = item.get("signals", {})
    ves = item.get("viral_entertainment_score", item.get("score", 0))
    lines.extend([
        f"## #{idx} Viral Entertainment Score: {ves}",
        "",
        f"- Time: `{item['start_time']:.1f}s` to `{item['end_time']:.1f}s`",
        f"- Duration: `{item['duration']:.1f}s`",
        f"- Title: {item['title']}",
        f"- Hook: {item['hook_sentence']}",
        f"- Why viral: {item['virality_reason']}",
        f"- Signals: hook={sigs.get('hook_score', 0)}, comedy={sigs.get('comedy_potential', 0)}, conflict={sigs.get('light_conflict', 0)}, absurdity={sigs.get('absurdity', 0)}, reaction={sigs.get('reaction_moment', 0)}, escalation={sigs.get('escalation', 0)}, payoff={sigs.get('payoff', 0)}, standalone={sigs.get('standalone', 0)}",
        f"- Subtitle: `{item['subtitle_file']}`",
        "",
    ])
(run_dir / "moments.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
print(run_dir / "result.json")
PY
}


analyze_visual_layouts() {
  local result_json="$1"
  local video_file="$2"
  local run_dir="$3"
  local cv_python

  cv_python="$(choose_cv_python)"
  [ -n "$cv_python" ] || die "Python not found for visual layout analyzer"
  "$cv_python" "$REPO_ROOT/scripts/visual_layout_analyzer.py" "$result_json" "$video_file" "$run_dir"
}


render_shorts() {
  local result_json="$1"
  local video_file="$2"
  local run_dir="$3"
  local ffmpeg_bin
  local ffmpeg_dir
  local crop_python
  local mpl_config_dir
  local crop_home_dir
  local shorts_dir

ffmpeg_bin="$(choose_ffmpeg)"
  [ -n "$ffmpeg_bin" ] || die "'ffmpeg' not found. Install it with: brew install ffmpeg"
  # Subtitle burning is disabled in optimized flow - skip subtitles filter check
  # if ! ffmpeg_has_subtitles_filter "$ffmpeg_bin"; then
  #   die "FFmpeg does not support the 'subtitles' filter: $ffmpeg_bin. Install/use ffmpeg-full, e.g. FFMPEG_BIN=/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
  # fi
  ffmpeg_dir="$(dirname "$ffmpeg_bin")"
  crop_python="$(choose_cv_python)"
  [ -n "$crop_python" ] || die "Python not found for PyAutoFlip rendering"
  [ -n "$video_file" ] || die "Video file is required for rendering"

  shorts_dir="$run_dir/shorts"
  mpl_config_dir="$run_dir/.matplotlib"
  crop_home_dir="$REPO_ROOT/.local-cache/pyautoflip-home"
  mkdir -p "$shorts_dir"
  mkdir -p "$mpl_config_dir"
  mkdir -p "$crop_home_dir"
  HOME="$crop_home_dir" MPLCONFIGDIR="$mpl_config_dir" PATH="$ffmpeg_dir:$PATH" "$crop_python" - "$result_json" "$video_file" "$shorts_dir" "$ffmpeg_bin" "$SMART_CROP_ENGINE" "$PYAUTOFLIP_METHOD" "$PYAUTOFLIP_PADDING" "$ASPECT_RATIO" <<'PY'
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from pyautoflip import reframe_video
except Exception as exc:
    raise SystemExit(
        "PyAutoFlip is not available. Install dependencies with: "
        "pip install -r requirements.txt"
    ) from exc

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
result_path = Path(sys.argv[1])
video_file = sys.argv[2]
shorts_dir = Path(sys.argv[3])
ffmpeg_bin = sys.argv[4]
smart_crop_engine = sys.argv[5].strip().lower() or "pyautoflip"
pyautoflip_method = sys.argv[6].strip() or "saliency"
pyautoflip_padding = sys.argv[7].strip() or "blur"
target_aspect_ratio = sys.argv[8].strip() or "9:16"
tmp_root = shorts_dir / ".pyautoflip_render"
if tmp_root.exists():
    try:
        shutil.rmtree(tmp_root)
    except Exception:
        pass  # Non-fatal - will be recreated
try:
    tmp_root.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # Non-fatal

if smart_crop_engine != "pyautoflip":
    raise SystemExit(f"Unsupported SMART_CROP_ENGINE={smart_crop_engine!r}; expected 'pyautoflip'")

def run_ffmpeg(cmd):
    subprocess.run(cmd, check=True)

def has_audio_stream(path):
    result = subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vn",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0

def filter_escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )

def resolve_subtitle_path(item):
    # Prefer ASS subtitle if available
    ass_subtitle = item.get("subtitle_ass_file")
    if ass_subtitle:
        ass_path = Path(str(ass_subtitle))
        if not ass_path.is_absolute():
            ass_path = result_path.parent / ass_subtitle
        if ass_path.exists():
            return ass_path
    
    # Fallback to SRT
    subtitle = item.get("subtitle_file")
    if not subtitle:
        return None
    path = Path(str(subtitle))
    if not path.is_absolute():
        path = result_path.parent / path
    return path if path.exists() else None

def final_video_filter(subtitle_path, skip_burn=False):
    # skip_burn=True when running before subtitle generation (optimized flow)
    # In that case, just scale without burning subtitles
    filters = [
        "scale=1080:1920:flags=lanczos",
        "setsar=1",
        "unsharp=5:5:0.55:3:3:0.25",
    ]
    if subtitle_path and not skip_burn:
        subtitle_path_obj = Path(subtitle_path)
        # Only apply force_style for non-ASS subtitles (SRT, etc.)
        # ASS files already have embedded styles from subtitle_ass_generator.py
        if subtitle_path_obj.suffix.lower() == ".ass":
            filters.append(
                f"subtitles=filename='{filter_escape(subtitle_path)}'"
            )
        else:
            style = "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=140"
            filters.append(
                f"subtitles=filename='{filter_escape(subtitle_path)}':force_style='{style}'"
            )
    return ",".join(filters)

shorts = []
for idx, item in enumerate(data.get("highlights", []), start=1):
    final_file = shorts_dir / f"short_{idx:02d}.mp4"
    source_clip = tmp_root / f"short_{idx:02d}_source.mp4"
    reframed_file = tmp_root / f"short_{idx:02d}_reframed.mp4"
    start = float(item["start_time"])
    end = float(item["end_time"])
    duration = max(0.01, end - start)

    run_ffmpeg([
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(start),
        "-i",
        video_file,
        "-t",
        str(duration),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(source_clip),
    ])

    if not has_audio_stream(source_clip):
        raise RuntimeError(f"Rendered source clip has no audio stream: {source_clip}")

    reframe_video(
        input_path=str(source_clip),
        output_path=str(reframed_file),
        target_aspect_ratio=target_aspect_ratio,
        detection_method=pyautoflip_method,
        padding_method=pyautoflip_padding,
    )

    subtitle_path = resolve_subtitle_path(item)
    run_ffmpeg([
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(reframed_file),
        "-i",
        str(source_clip),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        final_video_filter(subtitle_path, skip_burn=True),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(final_file),
    ])

    if not has_audio_stream(final_file):
        raise RuntimeError(f"Rendered short has no audio stream: {final_file}")

    merged = dict(item)
    merged["crop_plan"] = {
        "engine": "pyautoflip",
        "target_aspect_ratio": target_aspect_ratio,
        "method": pyautoflip_method,
        "padding_method": pyautoflip_padding,
        "subtitle_burned": bool(resolve_subtitle_path(item)),
    }
    merged["clip_url"] = str(final_file)
    merged["clip_path"] = str(final_file)
    shorts.append(merged)
    # Write result.json incrementally after each short to avoid losing data on crash
    data["shorts"] = shorts
    result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # Clean up temp files for this clip immediately after successful render
    for tmp_file in [source_clip, reframed_file]:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except Exception:
                pass

# Final cleanup of temp directory (defer to avoid hanging after successful render)
try:
    shutil.rmtree(tmp_root, ignore_errors=True)
except Exception:
    pass
PY
}


process_source() {
  local source="$1"
  local video_id
  local source_url
  local abs_output_dir
  local abs_transcript_dir
  local transcript_json
  local run_dir
  local video_file
  local result_json
  local total_steps

  video_id="$(video_id_from "$source")"
  source_url="$(source_url_for "$source" "$video_id")"
  abs_output_dir="$(absolute_path "$OUTPUT_DIR")"
  abs_transcript_dir="$(absolute_path "$TRANSCRIPT_DIR")"
  transcript_json="$abs_transcript_dir/$video_id/transcript.clean.json"
  run_dir="$abs_output_dir/$video_id"
  mkdir -p "$run_dir"

if [ "$SKIP_RENDER" = "0" ]; then
    total_steps=6
  else
    total_steps=4
  fi

  write_loading_state "$run_dir" "$video_id" "running" 0 "$total_steps" "Starting pipeline" "$source_url"
  write_loading_state "$run_dir" "$video_id" "running" 1 "$total_steps" "Preparing transcript" "Extracting or reusing YouTube captions"
  ensure_transcript "$source_url" "$video_id"

  write_loading_state "$run_dir" "$video_id" "running" 2 "$total_steps" "Preparing source video" "Downloading or reusing HD source"
  video_file="$(ensure_video "$source_url" "$video_id")"

  write_loading_state "$run_dir" "$video_id" "running" 3 "$total_steps" "Finding viral moments" "Scoring entertainment hooks, conflict, reaction, and payoff"
  result_json="$(analyze_moments "$video_id" "$source_url" "$transcript_json" "$run_dir")"
  log "Moments ready: $run_dir/moments.md"

if [ "$SKIP_RENDER" = "0" ]; then
    # OPTIMIZED FLOW: render first (fast, no subtitle burn), then generate subtitles (fast, transcribe 45-55s clips not full video)
    write_loading_state "$run_dir" "$video_id" "running" 4 "$total_steps" "Rendering shorts" "Cropping without subtitle (fast)"
    render_shorts "$result_json" "$video_file" "$run_dir"
    
# Subtitle generation removed - skipping ASS subtitle generation
    log "Shorts ready: $run_dir/shorts (subtitle generation disabled)"
  fi

  if [ "${DEFER_COMPLETED_STATE:-0}" != "1" ]; then
    write_loading_state "$run_dir" "$video_id" "completed" "$total_steps" "$total_steps" "Completed" "Final artifacts are ready"
  fi
}


main() {
  parse_args "$@"
  [ "${#SOURCES[@]}" -gt 0 ] || {
    usage
    die "At least one YouTube URL or video ID is required."
  }
  is_positive_int "$NUM_CLIPS" || die "--num-clips must be a positive integer."

  for source in "${SOURCES[@]}"; do
    process_source "$source"
  done

  log "Done."
}

main "$@"
