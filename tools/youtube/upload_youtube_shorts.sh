#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Where content-short stores rendered results
DEFAULT_BASE_DIR="$SCRIPT_DIR/storage/free-viral-shorts"

BASE_DIR="${BASE_DIR:-$DEFAULT_BASE_DIR}"

# This script uploads already-rendered shorts from content-short.
# It integrates with the Google OAuth + YouTube upload implementation
# from: /Users/agusrachman/Documents/Docker/n8n/download-clip
DOWNLOAD_CLIP_DIR="${DOWNLOAD_CLIP_DIR:-/Users/agusrachman/Documents/Docker/n8n/download-clip}"

# Optional venv for uploader. download-clip currently uses .venv by default.
DOWNLOAD_CLIP_VENV_PY="${DOWNLOAD_CLIP_VENV_PY:-$DOWNLOAD_CLIP_DIR/.venv/bin/python}"

VIDEO_ID_OR_RUN=""
VIDEO_FILE=""

TITLE=""
DESCRIPTION=""
TAGS=""              # comma-separated
PRIVACY="unlisted"  # public|unlisted|private
THUMBNAIL=""        # optional path
CATEGORY=""         # category name or id
LANGUAGE=""         # default language, e.g. id
HASHTAGS=""         # comma-separated or #tag list
PINNED_COMMENT=""
TARGET_AUDIENCE=""
CONTENT_WARNING=""
SOURCE_CREDIT=""

LOG_LEVEL="INFO"
DRY_RUN=0

log() { printf '[upload_youtube_shorts] %s\n' "$*" >&2; }
die() { printf '[upload_youtube_shorts] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage:
  ./${SCRIPT_NAME} -r <VIDEO_ID | run_dir> [options]

What it does:
  Upload content-short rendered shorts to YouTube using the uploader
  implementation from download-clip (youtube_upload.py).

You must have already rendered shorts in:
  storage/free-viral-shorts/<VIDEO_ID>/shorts/short_01.mp4

Options:
  -r, --run <VIDEO_ID|run_dir>
  --base-dir DIR                 Default: ${DEFAULT_BASE_DIR}

  --title TEXT                   YouTube title (default from moments.md / clip title if available)
  --description TEXT             YouTube description (will append #Shorts if missing)
  --tags "a,b,c"                Tags as comma-separated string
  --privacy public|unlisted|private   Default: unlisted
  --thumbnail FILE              Optional thumbnail image
  --video-file FILE             Upload this specific MP4 instead of shorts/short_*.mp4
  --category NAME|ID            YouTube category. Example: Entertainment or 24
  --language CODE               Default language. Example: id
  --hashtags "#shorts,#viral"   Hashtags appended to description
  --pinned-comment TEXT         Adds this as first/top-level comment after upload
  --target-audience TEXT        Appended to description metadata
  --content-warning TEXT        Appended to description metadata
  --source-credit TEXT          Appended to description metadata

  --dry-run                      Don't upload; just print what would be uploaded
  -h, --help

Examples:
  ./${SCRIPT_NAME} -r fVWowlAW928 \
    --title "Judul Channel" \
    --description "Deskripsi" \
    --tags "shorts,indonesia" \
    --privacy unlisted

  ./${SCRIPT_NAME} -r storage/free-viral-shorts/fVWowlAW928 --dry-run
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

python_has_upload_deps() {
  local candidate="$1"
  "$candidate" - <<'PY' >/dev/null 2>&1
import googleapiclient.discovery
import googleapiclient.http
import google.oauth2.credentials
import google.auth.transport.requests
PY
}

is_python_candidate_available() {
  local candidate="$1"
  if [[ "$candidate" == */* ]]; then
    [ -x "$candidate" ]
  else
    command -v "$candidate" >/dev/null 2>&1
  fi
}

choose_upload_python() {
  local candidate
  for candidate in \
    "$DOWNLOAD_CLIP_VENV_PY" \
    "$DOWNLOAD_CLIP_DIR/.venv/bin/python" \
    "$DOWNLOAD_CLIP_DIR/venv/bin/python" \
    "/opt/homebrew/bin/python3.11" \
    "python3.11" \
    "python3"
  do
    if is_python_candidate_available "$candidate" && python_has_upload_deps "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 0
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -r|--run)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        VIDEO_ID_OR_RUN="$2"
        shift 2
        ;;
      --base-dir)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        BASE_DIR="$2"
        shift 2
        ;;
      --title)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        TITLE="$2"
        shift 2
        ;;
      --description)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        DESCRIPTION="$2"
        shift 2
        ;;
      --tags)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        TAGS="$2"
        shift 2
        ;;
      --privacy)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        PRIVACY="$2"
        shift 2
        ;;
      --thumbnail)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        THUMBNAIL="$2"
        shift 2
        ;;
      --video-file)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        VIDEO_FILE="$2"
        shift 2
        ;;
      --category)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        CATEGORY="$2"
        shift 2
        ;;
      --language)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        LANGUAGE="$2"
        shift 2
        ;;
      --hashtags)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        HASHTAGS="$2"
        shift 2
        ;;
      --pinned-comment)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        PINNED_COMMENT="$2"
        shift 2
        ;;
      --target-audience)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        TARGET_AUDIENCE="$2"
        shift 2
        ;;
      --content-warning)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        CONTENT_WARNING="$2"
        shift 2
        ;;
      --source-credit)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        SOURCE_CREDIT="$2"
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
      *)
        die "Unknown option: $1"
        ;;
    esac
  done

  [ -n "$VIDEO_ID_OR_RUN" ] || die "Missing -r/--run"
}

resolve_run_dir() {
  local v="$1"
  # If it's already an absolute/relative path containing result.json, use it.
  if [[ "$v" == /* || "$v" == ./
        || "$v" == ../* ]]; then
    if [ -f "$v/result.json" ]; then
      printf '%s\n' "$(cd "$(dirname "$v")" && pwd)/$(basename "$v")"
      return
    fi
  fi

  # Otherwise assume it's a video id under BASE_DIR
  if [ -f "$BASE_DIR/$v/result.json" ]; then
    printf '%s\n' "${BASE_DIR}/$v"
    return
  fi

  # Also allow passing full path under BASE_DIR
  if [ -f "$BASE_DIR/$v/result.json" ]; then
    printf '%s\n' "${BASE_DIR}/$v"
    return
  fi

  die "Cannot resolve run dir. Expected $BASE_DIR/<VIDEO_ID>/result.json for: $v"
}

upload_all_shorts() {
  local run_dir="$1"
  local shots_dir="$run_dir/shorts"

  [ -d "$shots_dir" ] || die "Shorts dir not found: $shots_dir"

  local video_id="$(basename "$run_dir")"

  local py_bin
  py_bin="$(choose_upload_python)"
  [ -n "$py_bin" ] || die "No Python found with YouTube upload dependencies. Install google-api-python-client/google-auth in a venv, or set DOWNLOAD_CLIP_VENV_PY to the correct python path."

  # Collect shorts files (bash 3.2 on macOS doesn't always support mapfile/process substitution reliably)
  local files
  files="$(ls -1 "$shots_dir"/short_*.mp4 2>/dev/null | sort || true)"
  [ -n "$files" ] || die "No shorts found in $shots_dir (short_*.mp4)"


  log "Uploading shorts for run: $run_dir"
  log "Using upload Python: $py_bin"

  # Metadata resolution strategy:
  # - If user provided --title/--description/tags/privacy/thumbnail, apply to all shorts.
  # - Else, try to use moments.md for per-clip title/hook (best-effort).
  "$py_bin" - "$run_dir" "$video_id" "$shots_dir" "$DRY_RUN" "$TITLE" "$DESCRIPTION" "$TAGS" "$PRIVACY" "$THUMBNAIL" "$SCRIPT_DIR" "$DOWNLOAD_CLIP_DIR" "$CATEGORY" "$LANGUAGE" "$HASHTAGS" "$PINNED_COMMENT" "$TARGET_AUDIENCE" "$CONTENT_WARNING" "$SOURCE_CREDIT" "$VIDEO_FILE" <<'PY'
import os, re, json, sys, glob
from pathlib import Path

run_dir = Path(sys.argv[1])
video_id = sys.argv[2]
shots_dir = Path(sys.argv[3])
dry_run = sys.argv[4] == '1'
TITLE = sys.argv[5]
DESCRIPTION = sys.argv[6]
TAGS = sys.argv[7]
PRIVACY = sys.argv[8]
THUMBNAIL = sys.argv[9]
SCRIPT_DIR = Path(sys.argv[10])
DOWNLOAD_CLIP_DIR = Path(sys.argv[11])
CATEGORY = sys.argv[12]
LANGUAGE = sys.argv[13]
HASHTAGS = sys.argv[14]
PINNED_COMMENT = sys.argv[15]
TARGET_AUDIENCE = sys.argv[16]
CONTENT_WARNING = sys.argv[17]
SOURCE_CREDIT = sys.argv[18]
VIDEO_FILE = sys.argv[19]

# Direct uploader (independent dari download-clip OAuth path)
# Pakai token.json yang ada di content-short ini.
UPLOAD_MODULE_DIR = SCRIPT_DIR
sys.path.insert(0, str(UPLOAD_MODULE_DIR))

from youtube_upload_direct import upload_short

def split_csv(value):
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,\n]+", str(value)) if item.strip()]

def clean_hashtag(value):
    value = str(value or "").strip()
    if not value:
        return ""
    compact = re.sub(r"\\s+", "", value)
    return compact if compact.startswith("#") else f"#{compact}"

def merge_unique(*groups):
    out = []
    seen = set()
    for group in groups:
        for item in group or []:
            text = str(item).strip()
            if not text:
                continue
            key = text.lower()
            if key not in seen:
                seen.add(key)
                out.append(text)
    return out

def category_id(value):
    mapping = {
        "film": "1",
        "autos": "2",
        "music": "10",
        "pets": "15",
        "sports": "17",
        "travel": "19",
        "gaming": "20",
        "people": "22",
        "comedy": "23",
        "entertainment": "24",
        "news": "25",
        "howto": "26",
        "education": "27",
        "science": "28",
    }
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw if raw.isdigit() else mapping.get(raw.lower(), "")

def append_description_sections(description, *, hashtags=None, target_audience="", content_warning="", source_credit=""):
    parts = [str(description or "").strip()]
    if target_audience:
        parts.append(f"Target audience: {target_audience}")
    if content_warning:
        parts.append(f"Content warning: {content_warning}")
    if source_credit:
        parts.append(f"Source credit: {source_credit}")
    hashtag_line = " ".join([clean_hashtag(tag) for tag in (hashtags or []) if clean_hashtag(tag)])
    if hashtag_line:
        parts.append(hashtag_line)
    return "\n\n".join([part for part in parts if part]).strip()

def load_clip_list(path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("clips", "items", "highlights"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [data]
    return []

def load_result_highlights(run_dir):
    path = run_dir / "result.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    highlights = data.get("highlights") or []
    return highlights if isinstance(highlights, list) else []

def load_request_clips(run_dir):
    candidates = [
        run_dir / "request_metadata.json",
        run_dir / "sample_request.json",
        SCRIPT_DIR / "sample_request.json",
    ]
    seen = set()
    clips = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        for item in load_clip_list(path):
            clips.append(item)
    return clips

def first_number(*values):
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except Exception:
            continue
    return None

def item_start(item):
    return first_number(item.get("startSecond"), item.get("start_second"), item.get("start"), item.get("start_time"))

def item_end(item):
    return first_number(item.get("endSecond"), item.get("end_second"), item.get("end"), item.get("end_time"))

def find_request_clip(request_clips, idx, highlight_item):
    for item in request_clips:
        try:
            if int(item.get("clipNumber")) == idx:
                return item
        except Exception:
            pass

    h_start = item_start(highlight_item)
    h_end = item_end(highlight_item)
    if h_start is None or h_end is None:
        return {}

    best = None
    best_score = None
    for item in request_clips:
        r_start = item_start(item)
        r_end = item_end(item)
        if r_start is None or r_end is None:
            continue
        score = abs(r_start - h_start) + abs(r_end - h_end)
        overlaps = min(h_end, r_end) - max(h_start, r_start)
        if overlaps > 0:
            score -= overlaps
        if best is None or score < best_score:
            best = item
            best_score = score
    return best if best is not None and best_score is not None and best_score <= 10 else {}

def metadata_for_highlight(highlights, request_clips, idx):
    if idx <= 0 or idx > len(highlights):
        request_item = find_request_clip(request_clips, idx, {})
        yt = request_item.get("youtubeMetadata") if isinstance(request_item.get("youtubeMetadata"), dict) else {}
        return request_item or {}, yt
    item = highlights[idx - 1] if isinstance(highlights[idx - 1], dict) else {}
    yt = item.get("youtubeMetadata") if isinstance(item.get("youtubeMetadata"), dict) else {}
    if not yt:
        request_item = find_request_clip(request_clips, idx, item)
        request_yt = request_item.get("youtubeMetadata") if isinstance(request_item.get("youtubeMetadata"), dict) else {}
        if request_yt:
            merged = dict(request_item)
            merged.update({k: v for k, v in item.items() if v not in (None, "", [])})
            return merged, request_yt
    return item, yt

highlights = load_result_highlights(run_dir)
request_clips = load_request_clips(run_dir)


# Best-effort: parse moments.md to map clip index -> title/why/hook.
# moments.md usually contains blocks like "## #1 Score ..." then "- Title: ...".
moments_md = run_dir / 'moments.md'
clip_meta = {}
if moments_md.exists():
    text = moments_md.read_text(encoding='utf-8', errors='ignore')
    # split by clip headers
    # Example:
    # ## #1 Score 83
    # - Title: ...
    # - Hook: ...
    blocks = re.split(r"^##\s+#(\d+)\s+Score\s+.*$", text, flags=re.M)
    # blocks pattern: [pre, idx1, rest1, idx2, rest2,...]
    for i in range(1, len(blocks), 2):
        idx = int(blocks[i])
        rest = blocks[i+1]
        m_title = re.search(r"-\s*Title:\s*(.*)", rest)
        m_hook = re.search(r"-\s*Hook:\s*(.*)", rest)
        m_why = re.search(r"-\s*Why viral:\s*(.*)", rest)
        clip_meta[idx] = {
            'title': (m_title.group(1).strip() if m_title else ''),
            'hook': (m_hook.group(1).strip() if m_hook else ''),
            'why': (m_why.group(1).strip() if m_why else ''),
        }

if VIDEO_FILE.strip():
    candidate = Path(VIDEO_FILE.strip())
    if not candidate.is_absolute():
        candidate = SCRIPT_DIR / candidate
    if not candidate.exists():
        raise SystemExit(f'Video file not found: {candidate}')
    files = [str(candidate)]
else:
    files = sorted(glob.glob(str(shots_dir / 'short_*.mp4')))
if not files:
    raise SystemExit(f'No shorts found in {shots_dir}')

# Prepare common description
common_desc = DESCRIPTION or ''
if not common_desc and moments_md.exists():
    # fallback: use run title derived from video_id
    common_desc = ''

common_tags = None
if TAGS.strip():
    common_tags = [t.strip() for t in TAGS.split(',') if t.strip()]

for idx, fp in enumerate(files, start=1):
    clip_path = Path(fp)
    highlight_item, yt_meta = metadata_for_highlight(highlights, request_clips, idx)

    # Per-clip title/description fallback
    per_title = TITLE
    if not per_title:
        per_title = (
            yt_meta.get('title')
            or highlight_item.get('uploadTitle')
            or highlight_item.get('title')
            or clip_meta.get(idx, {}).get('title')
            or f"YouTube Short {video_id}"
        )

    per_desc = common_desc
    if not per_desc:
        per_desc = yt_meta.get('description') or highlight_item.get('description') or ''
    if not per_desc:
        why = highlight_item.get('viralReason') or highlight_item.get('virality_reason') or clip_meta.get(idx, {}).get('why')
        hook = highlight_item.get('hookLine') or highlight_item.get('hook_sentence') or clip_meta.get(idx, {}).get('hook')
        parts = []
        if hook: parts.append(f"Hook: {hook}")
        if why: parts.append(f"Why viral: {why}")
        per_desc = "\n".join(parts)

    yt_tags = yt_meta.get('tags') if isinstance(yt_meta.get('tags'), list) else []
    yt_hashtags = yt_meta.get('hashtags') if isinstance(yt_meta.get('hashtags'), list) else []
    cli_hashtags = split_csv(HASHTAGS)
    all_hashtags = merge_unique(cli_hashtags, yt_hashtags)
    per_desc = append_description_sections(
        per_desc,
        hashtags=all_hashtags,
        target_audience=TARGET_AUDIENCE or yt_meta.get('targetAudience', ''),
        content_warning=CONTENT_WARNING or yt_meta.get('contentWarning', ''),
        source_credit=SOURCE_CREDIT or yt_meta.get('sourceCredit', ''),
    )

    tags = common_tags or merge_unique(yt_tags, [tag.lstrip('#') for tag in all_hashtags], ['Shorts'])
    category = CATEGORY or yt_meta.get('category', '')
    language = LANGUAGE or yt_meta.get('language', '')
    pinned_comment = PINNED_COMMENT or yt_meta.get('pinnedComment', '')

    meta = {
        'title': per_title,
        'Deskripsi': per_desc,
        'tags': tags,
        'privacy': PRIVACY,
        'category': category,
        'language': language,
        'pinnedComment': pinned_comment,
    }

    if THUMBNAIL.strip():
        meta['Thumbnail'] = THUMBNAIL.strip()

    # Dry run mode
    if dry_run:
        print(json.dumps({
            'dry_run': True,
            'clip_index': idx,
            'clip_path': str(clip_path),
            'metadata': meta,
        }, ensure_ascii=False, indent=2))
        continue

    res = upload_short(str(clip_path), metadata=meta)
    print(json.dumps({
        'dry_run': False,
        'clip_index': idx,
        'video_id': res.get('video_id'),
        'upload_url': res.get('upload_url'),
    }, ensure_ascii=False))
PY
}

main() {
  parse_args "$@"
  run_dir="$(resolve_run_dir "$VIDEO_ID_OR_RUN")"
  upload_all_shorts "$run_dir"
}

main "$@"
