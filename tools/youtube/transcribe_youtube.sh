#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEFAULT_OUTPUT_DIR="storage/transcripts"
DEFAULT_LANGUAGES="id,en"
DEFAULT_PYTHON_BIN="python3.11"

OUTPUT_DIR="${OUTPUT_DIR:-$DEFAULT_OUTPUT_DIR}"
LANGUAGES="${LANGUAGES:-$DEFAULT_LANGUAGES}"
PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_PYTHON_BIN}"
VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/.venv-transcript-api}"
PREFER="${PREFER:-any}"
TRANSLATE_TO=""
PRESERVE_FORMATTING=0
SKIP_INSTALL=0
LIST_ONLY=0
URLS=()

log() {
  printf '[youtube-transcript] %s\n' "$*"
}

die() {
  printf '[youtube-transcript] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage:
  ./${SCRIPT_NAME} [options] <youtube-url-or-id> [youtube-url-or-id...]

Output:
  Default output folder: ${DEFAULT_OUTPUT_DIR}
  Each video gets a folder containing raw JSON, clean JSON, TXT, paragraphs,
  SRT, VTT, and metadata.

Options:
  -o, --output-dir DIR       Output folder. Default: ${DEFAULT_OUTPUT_DIR}
  -l, --languages LIST       Language priority, comma-separated. Default: ${DEFAULT_LANGUAGES}
                             Example: id,en or en,id
  --prefer MODE              Transcript type: any, manual, or generated. Default: any
  --translate-to CODE        Translate transcript using YouTube translation, for example en or id.
  --preserve-formatting      Preserve YouTube HTML formatting from captions.
  --list                     List available transcripts only, without writing transcript files.
  --skip-install             Do not install/update Python packages.
  -h, --help                 Show this help.

Examples:
  ./${SCRIPT_NAME} "https://youtu.be/VIDEO_ID"
  ./${SCRIPT_NAME} -l id,en --prefer manual "https://youtube.com/watch?v=VIDEO_ID"
  ./${SCRIPT_NAME} --translate-to en "https://youtu.be/VIDEO_ID"
  ./${SCRIPT_NAME} --list "https://youtu.be/VIDEO_ID"

Dependencies:
  Python 3.10-3.12 is required.
  The script creates ${VENV_DIR} and installs youtube-transcript-api unless
  --skip-install is used.

Note:
  This does not perform speech recognition. It extracts existing YouTube
  captions/subtitles, including auto-generated captions when available.
EOF
}

choose_python() {
  if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    return
  fi

  for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      return
    fi
  done

  die "Python not found. Install Python 3.10-3.12 first."
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -o|--output-dir)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        OUTPUT_DIR="$2"
        shift 2
        ;;
      -l|--languages|--language)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        LANGUAGES="$2"
        shift 2
        ;;
      --prefer)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        PREFER="$2"
        shift 2
        ;;
      --translate-to)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        TRANSLATE_TO="$2"
        shift 2
        ;;
      --preserve-formatting)
        PRESERVE_FORMATTING=1
        shift
        ;;
      --list)
        LIST_ONLY=1
        shift
        ;;
      --skip-install)
        SKIP_INSTALL=1
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

setup_environment() {
  choose_python

  if [ "$SKIP_INSTALL" = "0" ]; then
    if [ ! -d "$VENV_DIR" ]; then
      log "Creating Python environment: $VENV_DIR"
      "$PYTHON_BIN" -m venv "$VENV_DIR"
    fi

    log "Installing/updating youtube-transcript-api"
    "$VENV_DIR/bin/python" -m pip install -U pip wheel "setuptools<82"
    "$VENV_DIR/bin/python" -m pip install -U youtube-transcript-api
  fi

  [ -x "$VENV_DIR/bin/python" ] || die "Python environment not found: $VENV_DIR. Run without --skip-install first."
  "$VENV_DIR/bin/python" -c 'import youtube_transcript_api' >/dev/null 2>&1 ||
    die "youtube-transcript-api is not installed. Run without --skip-install first."
}

run_transcript_extractor() {
  "$VENV_DIR/bin/python" - "$@" <<'PY'
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import JSONFormatter, SRTFormatter, TextFormatter, WebVTTFormatter


NOISE_PATTERNS = [
    r"^\s*\[(music|musik|applause|tepuk tangan|laughter|tertawa|silence|noise|suara)\]\s*$",
    r"^\s*\((music|musik|applause|tepuk tangan|laughter|tertawa|silence|noise|suara)\)\s*$",
    r"^\s*♪+\s*$",
]

INLINE_NOISE_RE = re.compile(
    r"\s*[\[(]\s*("
    r"music|musik|applause|tepuk tangan|laughter|tertawa|silence|noise|suara|"
    r"bersorak|sorak|cheering|bernyanyi|singing|berteriak|shouting|laughs"
    r")\s*[\])]\s*",
    flags=re.IGNORECASE,
)


def video_id_from(value):
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    parsed = urlparse(value)
    host = parsed.netloc.lower().replace("www.", "")
    path_parts = [part for part in parsed.path.split("/") if part]

    if host in {"youtu.be"} and path_parts:
        return path_parts[0][:11]

    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if query_id:
        return query_id[:11]

    if host.endswith("youtube.com") and path_parts:
        if path_parts[0] in {"shorts", "embed", "live"} and len(path_parts) > 1:
            return path_parts[1][:11]

    match = re.search(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", value)
    if match:
        return match.group(1)

    raise ValueError(f"Cannot extract YouTube video id from: {value}")


def normalize_text(text, preserve_formatting=False):
    text = html.unescape(text or "")
    if not preserve_formatting:
        text = re.sub(r"<[^>]+>", "", text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\r", " ").replace("\n", " ")
    text = INLINE_NOISE_RE.sub(" ", text)
    text = re.sub(r"\s*♪+\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([({\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)}\]])", r"\1", text)
    text = re.sub(r"\b([A-Za-z])\s+'\s+([A-Za-z])", r"\1'\2", text)
    text = re.sub(r"\b([A-Za-z])\s+’\s+([A-Za-z])", r"\1’\2", text)
    return text.strip()


def is_noise(text):
    if not text:
        return True
    lowered = text.lower().strip()
    return any(re.match(pattern, lowered, flags=re.IGNORECASE) for pattern in NOISE_PATTERNS)


def dedupe_segments(segments):
    cleaned = []
    previous_text = ""

    for segment in segments:
        text = normalize_text(segment.get("text", ""))
        if is_noise(text):
            continue

        compact = re.sub(r"\W+", "", text.lower())
        previous_compact = re.sub(r"\W+", "", previous_text.lower())
        if compact and compact == previous_compact:
            continue

        cleaned.append(
            {
                "text": text,
                "start": round(float(segment.get("start", 0.0)), 3),
                "duration": round(float(segment.get("duration", 0.0)), 3),
                "end": round(float(segment.get("start", 0.0)) + float(segment.get("duration", 0.0)), 3),
            }
        )
        previous_text = text

    return cleaned


def sentence_text(segments):
    text = " ".join(segment["text"] for segment in segments)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def paragraph_text(segments, max_gap=1.8, max_chars=720):
    paragraphs = []
    current = []
    current_chars = 0
    previous_end = None

    for segment in segments:
        gap = 0 if previous_end is None else segment["start"] - previous_end
        should_break = current and (gap > max_gap or current_chars + len(segment["text"]) > max_chars)

        if should_break:
            paragraphs.append(sentence_text(current))
            current = []
            current_chars = 0

        current.append(segment)
        current_chars += len(segment["text"]) + 1
        previous_end = segment["end"]

    if current:
        paragraphs.append(sentence_text(current))

    return "\n\n".join(paragraphs).strip() + "\n"


def fmt_ts(seconds, sep=","):
    seconds = max(0.0, float(seconds))
    millis = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    if millis == 1000:
        total += 1
        millis = 0
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{millis:03d}"


def write_srt(path, segments):
    with path.open("w", encoding="utf-8") as handle:
        for index, segment in enumerate(segments, start=1):
            handle.write(f"{index}\n")
            handle.write(f"{fmt_ts(segment['start'])} --> {fmt_ts(segment['end'])}\n")
            handle.write(f"{segment['text']}\n\n")


def write_vtt(path, segments):
    with path.open("w", encoding="utf-8") as handle:
        handle.write("WEBVTT\n\n")
        for segment in segments:
            handle.write(f"{fmt_ts(segment['start'], '.')} --> {fmt_ts(segment['end'], '.')}\n")
            handle.write(f"{segment['text']}\n\n")


def parse_srt_timestamp(value):
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    hours, minutes, seconds, millis = [int(part) for part in match.groups()]
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def parse_srt(path):
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\n\s*\n", raw.strip())
    segments = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_idx = next((idx for idx, line in enumerate(lines) if "-->" in line), None)
        if timing_idx is None:
            continue
        start_raw, end_raw = [part.strip().split()[0] for part in lines[timing_idx].split("-->", 1)]
        text = normalize_text(" ".join(lines[timing_idx + 1 :]))
        if not text or is_noise(text):
            continue
        start = parse_srt_timestamp(start_raw)
        end = max(start + 0.25, parse_srt_timestamp(end_raw))
        segments.append({"text": text, "start": start, "duration": end - start})
    return segments


def parse_vtt_timestamp(value):
    value = value.strip()
    match = re.fullmatch(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})", value)
    if not match:
        raise ValueError(f"Invalid VTT timestamp: {value}")
    hours_raw, minutes, seconds, millis = match.groups()
    hours = int(hours_raw or 0)
    return hours * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_vtt(path):
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    segments = []
    block = []

    def flush(lines):
        if not lines:
            return
        timing_idx = next((idx for idx, line in enumerate(lines) if "-->" in line), None)
        if timing_idx is None:
            return
        start_raw, end_raw = [part.strip().split()[0] for part in lines[timing_idx].split("-->", 1)]
        text_lines = []
        for line in lines[timing_idx + 1 :]:
            if not line or line.startswith(("NOTE", "STYLE", "REGION")):
                continue
            text_lines.append(line)
        text = normalize_text(" ".join(text_lines))
        if not text or is_noise(text):
            return
        start = parse_vtt_timestamp(start_raw)
        end = max(start + 0.25, parse_vtt_timestamp(end_raw))
        segments.append({"text": text, "start": start, "duration": end - start})

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            flush(block)
            block = []
            continue
        if stripped == "WEBVTT" or stripped.startswith(("Kind:", "Language:", "X-TIMESTAMP-MAP")):
            continue
        block.append(stripped)
    flush(block)

    return segments


def transcript_to_raw_data(fetched_transcript):
    if hasattr(fetched_transcript, "to_raw_data"):
        return fetched_transcript.to_raw_data()
    return [
        {"text": item["text"], "start": item["start"], "duration": item["duration"]}
        if isinstance(item, dict)
        else {"text": item.text, "start": item.start, "duration": item.duration}
        for item in fetched_transcript
    ]


def pick_transcript(transcript_list, languages, prefer):
    if prefer == "manual":
        return transcript_list.find_manually_created_transcript(languages)
    if prefer == "generated":
        return transcript_list.find_generated_transcript(languages)
    return transcript_list.find_transcript(languages)


def list_transcripts(ytt_api, video_id):
    transcript_list = ytt_api.list(video_id)
    rows = []
    for transcript in transcript_list:
        translation_languages = [
            {
                "language": item.language,
                "language_code": item.language_code,
            }
            for item in transcript.translation_languages
        ]
        rows.append(
            {
                "video_id": transcript.video_id,
                "language": transcript.language,
                "language_code": transcript.language_code,
                "is_generated": transcript.is_generated,
                "is_translatable": transcript.is_translatable,
                "translation_languages": translation_languages,
            }
        )
    return rows


def ytdlp_sub_langs(languages):
    expanded = []
    for language in languages:
        expanded.append(language)
        expanded.append(f"{language}.*")
    return ",".join(dict.fromkeys(expanded))


def pick_subtitle_file(files, languages):
    if not files:
        raise ValueError("No .vtt/.srt subtitle file found")
    for language in languages:
        for path in files:
            name = path.name.lower()
            if f".{language.lower()}." in name or name.endswith(f".{language.lower()}.vtt") or name.endswith(f".{language.lower()}.srt"):
                return path
    return files[0]


def parse_subtitle_file(path):
    if path.suffix.lower() == ".vtt":
        return parse_vtt(path)
    if path.suffix.lower() == ".srt":
        return parse_srt(path)
    raise ValueError(f"Unsupported subtitle file: {path}")


def find_local_subtitle(args, video_id, languages):
    roots = [
        Path(args.output_dir) / video_id,
        Path.cwd() / "storage" / "video",
        Path.cwd() / "storage" / "transcripts" / video_id,
    ]
    files = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(root.glob(f"*{video_id}*.vtt"))
        files.extend(root.glob(f"*{video_id}*.srt"))
        files.extend(root.glob("*.vtt"))
        files.extend(root.glob("*.srt"))
    files = sorted({path.resolve() for path in files if path.is_file()})
    return pick_subtitle_file(files, languages) if files else None


def fetch_segments_with_ytdlp(args, source, video_id, languages):
    local_subtitle = find_local_subtitle(args, video_id, languages)
    if local_subtitle:
        raw_segments = parse_subtitle_file(local_subtitle)
        if raw_segments:
            return raw_segments, local_subtitle, f"local subtitle cache: {local_subtitle}"

    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        raise ValueError("yt-dlp is required for fallback subtitles. Install it with: brew install yt-dlp")

    out_dir = Path(args.output_dir) / video_id
    work_dir = out_dir / ".yt-dlp-subtitles"
    work_dir.mkdir(parents=True, exist_ok=True)

    for old_file in work_dir.glob("*"):
        if old_file.is_file():
            old_file.unlink()

    cmd = [
        ytdlp,
        "--no-playlist",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        ytdlp_sub_langs(languages),
        "--sub-format",
        "vtt/best",
        "--convert-subs",
        "vtt",
        "-o",
        str(work_dir / "%(id)s.%(ext)s"),
        source,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    subtitle_files = sorted([*work_dir.glob(f"{video_id}*.vtt"), *work_dir.glob(f"{video_id}*.srt")])
    if completed.returncode != 0 and not subtitle_files:
        message = (completed.stderr or completed.stdout or "").strip()
        raise ValueError(f"yt-dlp subtitle fallback failed: {message}")

    selected_subtitle = pick_subtitle_file(subtitle_files, languages)
    raw_segments = parse_subtitle_file(selected_subtitle)
    if not raw_segments:
        raise ValueError(f"yt-dlp subtitle fallback produced an empty transcript: {selected_subtitle}")
    return raw_segments, selected_subtitle, completed.stderr or completed.stdout or ""


def persist_outputs(
    args,
    source,
    video_id,
    languages,
    raw_segments,
    selected_meta,
    available,
    source_method,
    formatter_payload=None,
    fallback_vtt_path=None,
    fallback_log="",
    api_error="",
):
    clean_segments = dedupe_segments(raw_segments)
    out_dir = Path(args.output_dir) / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_json = out_dir / "transcript.raw.json"
    clean_json = out_dir / "transcript.clean.json"
    metadata_json = out_dir / "metadata.json"

    raw_json.write_text(json.dumps(raw_segments, ensure_ascii=False, indent=2), encoding="utf-8")
    clean_json.write_text(json.dumps(clean_segments, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "transcript.txt").write_text(sentence_text(clean_segments) + "\n", encoding="utf-8")
    (out_dir / "transcript.paragraphs.txt").write_text(paragraph_text(clean_segments), encoding="utf-8")
    write_srt(out_dir / "transcript.srt", clean_segments)
    write_vtt(out_dir / "transcript.vtt", clean_segments)

    if formatter_payload:
        (out_dir / "youtube_formatter.raw.json").write_text(formatter_payload["json"], encoding="utf-8")
        (out_dir / "youtube_formatter.raw.txt").write_text(formatter_payload["txt"], encoding="utf-8")
        (out_dir / "youtube_formatter.raw.srt").write_text(formatter_payload["srt"], encoding="utf-8")
        (out_dir / "youtube_formatter.raw.vtt").write_text(formatter_payload["vtt"], encoding="utf-8")
    elif fallback_vtt_path:
        (out_dir / "yt_dlp.raw.vtt").write_text(Path(fallback_vtt_path).read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        (out_dir / "yt_dlp.raw.txt").write_text(sentence_text(clean_segments) + "\n", encoding="utf-8")

    metadata = {
        "source": source,
        "video_id": video_id,
        "source_method": source_method,
        "requested_languages": languages,
        "prefer": args.prefer,
        "selected_transcript": selected_meta,
        "available_transcripts": available,
        "raw_segment_count": len(raw_segments),
        "clean_segment_count": len(clean_segments),
        "api_error": api_error,
        "fallback_vtt": str(fallback_vtt_path) if fallback_vtt_path else None,
        "fallback_log": fallback_log[-4000:] if fallback_log else "",
        "outputs": {
            "raw_json": str(raw_json),
            "clean_json": str(clean_json),
            "text": str(out_dir / "transcript.txt"),
            "paragraphs": str(out_dir / "transcript.paragraphs.txt"),
            "srt": str(out_dir / "transcript.srt"),
            "vtt": str(out_dir / "transcript.vtt"),
        },
    }
    metadata_json.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[youtube-transcript] Transcript ready: {out_dir}")
    print(f"[youtube-transcript] Source method: {source_method}")
    print(f"[youtube-transcript] Selected: {selected_meta.get('language_code')} generated={selected_meta.get('is_generated')}")


def write_outputs(args, source, video_id):
    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    if not languages:
        raise ValueError("At least one language code is required.")

    ytt_api = YouTubeTranscriptApi()
    available = list_transcripts(ytt_api, video_id)

    if args.list_only:
        print(json.dumps({"video_id": video_id, "available_transcripts": available}, ensure_ascii=False, indent=2))
        return

    transcript_list = ytt_api.list(video_id)
    transcript = pick_transcript(transcript_list, languages, args.prefer)

    selected_meta = {
        "video_id": transcript.video_id,
        "language": transcript.language,
        "language_code": transcript.language_code,
        "is_generated": transcript.is_generated,
        "is_translatable": transcript.is_translatable,
        "translated_to": None,
    }

    if args.translate_to:
        transcript = transcript.translate(args.translate_to)
        selected_meta["translated_to"] = args.translate_to

    fetched = transcript.fetch(preserve_formatting=args.preserve_formatting)
    raw_segments = transcript_to_raw_data(fetched)

    formatter_payload = {
        "json": JSONFormatter().format_transcript(fetched),
        "txt": TextFormatter().format_transcript(fetched),
        "srt": SRTFormatter().format_transcript(fetched),
        "vtt": WebVTTFormatter().format_transcript(fetched),
    }
    persist_outputs(args, source, video_id, languages, raw_segments, selected_meta, available, "youtube-transcript-api", formatter_payload=formatter_payload)


def write_outputs_from_ytdlp(args, source, video_id, api_error):
    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    if not languages:
        raise ValueError("At least one language code is required.")

    raw_segments, selected_vtt, fallback_log = fetch_segments_with_ytdlp(args, source, video_id, languages)
    language_code = "unknown"
    for language in languages:
        if f".{language}." in selected_vtt.name or selected_vtt.name.endswith(f".{language}.vtt"):
            language_code = language
            break
    selected_meta = {
        "video_id": video_id,
        "language": language_code,
        "language_code": language_code,
        "is_generated": True,
        "is_translatable": False,
        "translated_to": None,
    }
    persist_outputs(
        args,
        source,
        video_id,
        languages,
        raw_segments,
        selected_meta,
        [],
        "yt-dlp-subtitle-fallback",
        fallback_vtt_path=selected_vtt,
        fallback_log=fallback_log,
        api_error=api_error,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--languages", required=True)
    parser.add_argument("--prefer", choices=["any", "manual", "generated"], required=True)
    parser.add_argument("--translate-to", default="")
    parser.add_argument("--preserve-formatting", action="store_true")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("sources", nargs="+")
    args = parser.parse_args()

    failed = False
    for source in args.sources:
        video_id = video_id_from(source)
        try:
            write_outputs(args, source, video_id)
        except Exception as exc:
            api_error = str(exc)
            print(f"[youtube-transcript] API failed for {source}; trying yt-dlp subtitle fallback.", file=sys.stderr)
            print(f"[youtube-transcript] API error: {api_error}", file=sys.stderr)
            if args.list_only:
                failed = True
                continue
            try:
                write_outputs_from_ytdlp(args, source, video_id, api_error)
            except Exception as fallback_exc:
                failed = True
                print(f"[youtube-transcript] ERROR for {source}: {fallback_exc}", file=sys.stderr)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
PY
}

main() {
  parse_args "$@"

  [ "${#URLS[@]}" -gt 0 ] || {
    usage
    die "At least one YouTube URL or video ID is required."
  }

  case "$PREFER" in
    any|manual|generated) ;;
    *) die "--prefer must be one of: any, manual, generated." ;;
  esac

  mkdir -p "$OUTPUT_DIR"
  setup_environment

  log "Output dir: $OUTPUT_DIR"
  log "Languages: $LANGUAGES"
  log "Prefer: $PREFER"
  log "URLs: ${#URLS[@]}"

  local args=(
    --output-dir "$OUTPUT_DIR"
    --languages "$LANGUAGES"
    --prefer "$PREFER"
  )

  if [ -n "$TRANSLATE_TO" ]; then
    args+=(--translate-to "$TRANSLATE_TO")
  fi

  if [ "$PRESERVE_FORMATTING" = "1" ]; then
    args+=(--preserve-formatting)
  fi

  if [ "$LIST_ONLY" = "1" ]; then
    args+=(--list-only)
  fi

  run_transcript_extractor "${args[@]}" "${URLS[@]}"
  log "Done."
}

main "$@"
