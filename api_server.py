#!/usr/bin/env python3
"""
Content Short API Server
FastAPI async server for n8n integration with content-short CLI.
"""

import os
import re
import sys
import time
import uuid
import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, status, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# Import subtitle service
from subtitle_service.config import get_settings as get_subtitle_settings
from subtitle_service.api import create_subtitle_router as create_subtitle_router_raw
from transcript_utils import find_downloaded_video, convert_word_timestamps_to_transcript_files

app = FastAPI(
    title="Content Short API",
    description="Async API for content-short CLI pipeline",
    version="1.0.0"
)

# Include subtitle router if enabled
subtitle_settings = get_subtitle_settings()
if subtitle_settings.enable_subtitle_api:
    subtitle_router = create_subtitle_router_raw()
    app.include_router(subtitle_router)
    print(f"✅ Subtitle API enabled on port {subtitle_settings.subtitle_api_port}")
else:
    print("ℹ️  Subtitle API disabled. Set ENABLE_SUBTITLE_API=true to enable.")

security = HTTPBearer(auto_error=False)

# Configuration
# Default to local repo paths, can be overridden via env vars
DEFAULT_APP_DIR = Path(__file__).resolve().parent
APP_DIR = Path(os.environ.get("CONTENT_SHORT_APP_DIR", DEFAULT_APP_DIR)).resolve()
CONTENT_SHORT_DIR = APP_DIR
STORAGE_DIR = Path(
    os.environ.get("CONTENT_SHORT_STORAGE_DIR", APP_DIR / "storage")
).resolve()
OUTPUT_DIR = STORAGE_DIR / "free-viral-shorts"
TRANSCRIPT_DIR = STORAGE_DIR / "transcripts"
VIDEO_DIR = STORAGE_DIR / "video"
API_JOBS_DIR = STORAGE_DIR / "api-jobs"

API_TOKEN = os.environ.get("CONTENT_SHORT_API_TOKEN", "change-me")
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "/usr/bin/ffmpeg")
CV_PYTHON_BIN = os.environ.get("CV_PYTHON_BIN", sys.executable)

THUMBNAIL_ASSET_DIR = APP_DIR / "assets" / "thumbnail"
THUMBNAIL_ASSET_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

def find_static_opening_thumbnail(video_id: str) -> Optional[Path]:
    for ext in THUMBNAIL_ASSET_EXTENSIONS:
        path = THUMBNAIL_ASSET_DIR / f"{video_id}{ext}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def is_opening_watermarked_input(path: Path) -> bool:
    return (
        path.is_file()
        and path.name.endswith("_wm.mp4")
        and "_telegram" not in path.stem
        and path.stat().st_size > 0
    )


def find_opening_watermarked_inputs(run_dir: Path) -> list[Path]:
    watermarked_dir = run_dir / "watermarked"
    if not watermarked_dir.exists():
        return []
    return sorted(path for path in watermarked_dir.glob("*_wm.mp4") if is_opening_watermarked_input(path))

# Python binary for audio fallback transcription (needs whisper installed)
# Priority: SUBTITLE_AUTOCAPTIONS_PYTHON env > VENV_DIR bin/python > explicit transcript venv
TRANSCRIPT_VENV_DIR = os.environ.get("VENV_DIR", str(APP_DIR / ".venv-transcript-api"))
FALLBACK_PYTHON_BIN = os.environ.get(
    "SUBTITLE_AUTOCAPTIONS_PYTHON",
    str(Path(TRANSCRIPT_VENV_DIR) / "bin" / "python")
)

CONTENT_SHORT_BASE_URL = os.environ.get(
    "CONTENT_SHORT_BASE_URL",
    os.environ.get("WEBHOOK_URL", "http://content-short-api:8080")
)

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
API_JOBS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job store (use Redis for production)
jobs = {}


def load_job_metadata(job_id: str) -> Optional[dict]:
    """Load job metadata from disk."""
    metadata_file = API_JOBS_DIR / f"{job_id}.json"
    if metadata_file.exists():
        try:
            return json.loads(metadata_file.read_text())
        except Exception:
            pass
    return None


def save_job_metadata(job_id: str, metadata: dict):
    """Save job metadata to disk."""
    metadata_file = API_JOBS_DIR / f"{job_id}.json"
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))


def find_active_step_jobs(video_id: str, step: str) -> list[dict]:
    """Return queued/running jobs for the same video and step."""
    active_statuses = {"queued", "running"}
    active_jobs = []

    for job in jobs.values():
        if (
            job.get("video_id") == video_id
            and job.get("step") == step
            and job.get("status") in active_statuses
        ):
            active_jobs.append(job)

    for metadata_file in API_JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(metadata_file.read_text())
        except Exception:
            continue

        if (
            job.get("video_id") == video_id
            and job.get("step") == step
            and job.get("status") in active_statuses
        ):
            if not any(item.get("job_id") == job.get("job_id") for item in active_jobs):
                active_jobs.append(job)

    return active_jobs


def normalize_process_output(value) -> str:
    """Normalize process output to string.

    Handles None, bytes, and str inputs.
    - None becomes empty string
    - bytes are decoded with utf-8 (errors replaced)
    - str remains str
    - other objects are converted to str
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def combine_process_output(stdout, stderr) -> str:
    """Combine stdout and stderr into single output string.

    Both arguments are normalized before combining.
    """
    parts = [
        normalize_process_output(stdout),
        normalize_process_output(stderr),
    ]
    return "\n".join(part for part in parts if part)


def save_job_process_logs(job_id: str, stdout, stderr) -> dict:
    """Save full stdout/stderr to log files.

    Returns dict with paths to log files (relative to STORAGE_DIR).
    Handles None, bytes, and str inputs.
    """
    log_paths = {}

    # Normalize stdout
    stdout_str = normalize_process_output(stdout)
    if stdout_str:
        stdout_file = API_JOBS_DIR / f"{job_id}.stdout.log"
        stdout_file.write_text(stdout_str)
        log_paths["stdout_log"] = str(stdout_file.relative_to(STORAGE_DIR))

    # Normalize stderr
    stderr_str = normalize_process_output(stderr)
    if stderr_str:
        stderr_file = API_JOBS_DIR / f"{job_id}.stderr.log"
        stderr_file.write_text(stderr_str)
        log_paths["stderr_log"] = str(stderr_file.relative_to(STORAGE_DIR))

    return log_paths


def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """Verify Bearer token. Returns 401 if missing or invalid."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    if credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return credentials.credentials


def validate_mp4_file(file_path: Path) -> tuple[bool, Optional[str]]:
    """
    Validate MP4 file exists and is readable with valid duration.
    Returns (is_valid, error_message).

    Checks:
    - File exists
    - File size > 0
    - ffprobe can read the file
    - Duration > 0
    """
    if not file_path.exists():
        return (False, f"File does not exist: {file_path}")

    if file_path.stat().st_size == 0:
        return (False, f"File is empty: {file_path}")

    # Use ffprobe to check duration
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(file_path)
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return (False, f"ffprobe failed for {file_path}: {result.stderr}")

        try:
            data = json.loads(result.stdout)
            duration = data.get("format", {}).get("duration")
            if duration is None:
                return (False, f"No duration found in {file_path}")
            if float(duration) <= 0:
                return (False, f"Invalid duration in {file_path}: {duration}")
        except (json.JSONDecodeError, ValueError) as e:
            return (False, f"Cannot parse ffprobe output for {file_path}: {e}")

    except subprocess.TimeoutExpired:
        return (False, f"ffprobe timed out for {file_path}")
    except Exception as e:
        return (False, f"ffprobe error for {file_path}: {e}")

    return (True, None)


def validate_audio_stream(file_path: Path) -> tuple[bool, Optional[str]]:
    """Validate that an MP4 has at least one audio stream."""
    if not file_path.exists():
        return (False, f"File does not exist: {file_path}")

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "json",
                str(file_path)
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return (False, f"ffprobe audio check failed for {file_path}: {result.stderr}")

        data = json.loads(result.stdout)
        if not data.get("streams"):
            return (False, f"No audio stream found in {file_path}")

        return (True, None)
    except subprocess.TimeoutExpired:
        return (False, f"ffprobe audio check timed out for {file_path}")
    except Exception as e:
        return (False, f"ffprobe audio check error for {file_path}: {e}")


def validate_opening_result(run_dir: Path) -> tuple[bool, Optional[str]]:
    """
    Validate opening step result by checking watermarked/*_wm.mp4 directly.

    The opening narrator script:
    1. Creates temporary opening video in opening/ directory
    2. Merges with the non-Telegram watermarked video
    3. Overwrites watermarked/short_XX_wm.mp4 with the merged result
    4. Attempts to clean up opening/ directory

    Telegram delivery variants are intentionally ignored.
    """
    watermarked_dir = run_dir / "watermarked"
    if not watermarked_dir.exists():
        return (False, f"watermarked directory does not exist: {watermarked_dir}")

    mp4_files = find_opening_watermarked_inputs(run_dir)
    if not mp4_files:
        return (False, f"No non-Telegram *_wm.mp4 files found in {watermarked_dir}")

    # Validate each short - at least one must be valid
    valid_outputs = 0
    for short_path in mp4_files:
        is_valid, error = validate_mp4_file(short_path)
        if not is_valid:
            continue

        has_audio, audio_error = validate_audio_stream(short_path)
        if not has_audio:
            continue

        valid_outputs += 1

    if valid_outputs <= 0:
        return (False, "No valid short video with duration and audio found")

    return (True, None)




def _log_fallback(msg: str) -> None:
    """Print a timestamped fallback log line."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[audio-fallback {ts}] {msg}", flush=True)


def run_audio_fallback_transcription(
    video_id: str,
    video_path: Path,
    language: str = "id",
) -> Path:
    """Run audio fallback transcription using Whisper.

    Args:
        video_id: The YouTube video ID
        video_path: Path to the downloaded video file
        language: Language code for transcription (e.g., "id", "en")

    Returns:
        Path to the word_timestamps.json file

    Raises:
        RuntimeError: If transcription fails
    """
    transcript_dir = TRANSCRIPT_DIR / video_id
    transcript_dir.mkdir(parents=True, exist_ok=True)

    audio_path = transcript_dir / "audio.wav"
    word_timestamps_path = transcript_dir / "word_timestamps.json"

    # Build command to run caption_generator.py
    # Use FALLBACK_PYTHON_BIN which has whisper installed (transcript venv)
    cmd = [
        FALLBACK_PYTHON_BIN,
        str(APP_DIR / "external_packages/auto-captions/caption_generator.py"),
        "-i", str(video_path),
        "-a", str(audio_path),
        "-o", str(word_timestamps_path),
        "-m", "medium",
        "-l", language,
        "--preset", "accurate",
        "--audio-preset", "speech",
        "--save-raw-result",
    ]

    # First language from request.languages (e.g., "id" from "id,en")
    if "," in language:
        first_lang = language.split(",")[0].strip()
        if first_lang:
            cmd[cmd.index("-l") + 1] = first_lang

    video_size_mb = video_path.stat().st_size / (1024 * 1024)
    _log_fallback(f"Starting Whisper transcription for {video_id}")
    _log_fallback(f"  Video: {video_path.name} ({video_size_mb:.1f} MB)")
    _log_fallback(f"  Language: {language}, Model: medium, Preset: accurate")
    _log_fallback(f"  Command: {' '.join(cmd)}")

    t0 = time.monotonic()

    try:
        # Use Popen to stream output in real-time
        process = subprocess.Popen(
            cmd,
            cwd=str(APP_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line-buffered
        )

        output_lines = []
        for line in process.stdout:
            line = line.rstrip("\n")
            output_lines.append(line)
            # Forward all caption_generator output to server logs
            print(f"  [whisper] {line}", flush=True)

        process.wait(timeout=1800)  # 30 minute timeout for wait
        elapsed = time.monotonic() - t0
        combined_output = "\n".join(output_lines)

        if process.returncode != 0:
            _log_fallback(f"Whisper process FAILED (exit={process.returncode}) after {elapsed:.1f}s")
            raise RuntimeError(
                f"Audio fallback transcription failed (exit={process.returncode}, {elapsed:.1f}s): {combined_output[-2000:]}"
            )

        if not word_timestamps_path.exists():
            _log_fallback(f"Whisper process exited OK but word_timestamps.json NOT found after {elapsed:.1f}s")
            raise RuntimeError(
                f"Audio fallback completed but word_timestamps.json not found at {word_timestamps_path}"
            )

        wt_size = word_timestamps_path.stat().st_size / 1024
        _log_fallback(f"Whisper transcription SUCCESS in {elapsed:.1f}s, output {wt_size:.1f} KB")
        return word_timestamps_path

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        _log_fallback(f"Whisper process TIMED OUT after {elapsed:.1f}s")
        process.kill()
        process.wait()
        raise RuntimeError(f"Audio fallback transcription timed out after {elapsed:.1f}s")





def step_output_exists(step: str, video_id: str) -> bool:
    """
    Check if output exists for a specific step.
    Returns True only if expected output for the step exists and is valid.
    """
    run_dir = OUTPUT_DIR / video_id

    if step == "download":
        # yt-dlp output includes title/date before the video id, for example:
        # 2024-04-17_Title_lo6KE0Kcvoc.mp4
        if VIDEO_DIR.exists():
            for pattern in (
                f"{video_id}.*",
                f"*{video_id}*.mp4",
                f"*{video_id}*.mkv",
                f"*{video_id}*.webm",
                f"*{video_id}*.mov",
            ):
                files = [
                    file_path
                    for file_path in VIDEO_DIR.glob(pattern)
                    if file_path.is_file() and file_path.stat().st_size > 0
                ]
                if files:
                    return True
        return False

    elif step == "transcript":
        # Check for specific required transcript files
        transcript_dir = TRANSCRIPT_DIR / video_id
        required_files = [
            transcript_dir / "transcript.clean.json",
            transcript_dir / "transcript.txt",
            transcript_dir / "transcript.vtt",
        ]
        return all(path.exists() and path.stat().st_size > 0 for path in required_files)

    elif step == "analyze":
        # Check for moments.md or result.json in run dir
        if run_dir.exists():
            if (run_dir / "moments.md").exists():
                return True
            if (run_dir / "result.json").exists():
                return True
        return False

    elif step == "render":
        # Check shorts/*.mp4 with valid duration
        shorts_dir = run_dir / "shorts"
        if shorts_dir.exists():
            mp4_files = list(shorts_dir.glob("*.mp4"))
            for f in mp4_files:
                is_valid, _ = validate_mp4_file(f)
                has_audio, _ = validate_audio_stream(f)
                if is_valid and has_audio:
                    return True
        return False

    elif step == "opening":
        is_valid, _ = validate_opening_result(run_dir)
        return is_valid

    elif step == "watermark":
        # Check watermarked/*_wm.mp4 with valid duration
        watermarked_dir = run_dir / "watermarked"
        if watermarked_dir.exists():
            wm_files = list(watermarked_dir.glob("*_wm.mp4"))
            for f in wm_files:
                is_valid, _ = validate_mp4_file(f)
                if is_valid:
                    return True
        return False

# Unknown step - fall back to generic check
    return check_output_exists(video_id)


def read_watermark_plan_error(video_id: str) -> Optional[str]:
    """
    Read error from watermark_plan.json if present.
    Returns error message if found, None otherwise.
    """
    run_dir = OUTPUT_DIR / video_id
    plan_file = run_dir / "watermark_plan.json"

    if not plan_file.exists():
        return None

    try:
        plan_data = json.loads(plan_file.read_text())

# Check for error in clips/items
        clips = plan_data.get("clips", []) if isinstance(plan_data, dict) else []
        for clip in clips:
            if isinstance(clip, dict) and clip.get("error"):
                return clip.get("error")

        # Check for top-level error
        if plan_data.get("error"):
            return plan_data.get("error")

    except Exception:
        pass

    return None


def load_transcribe_text(video_id: str) -> Optional[str]:
    """
    Load full transcript text for a video.

    Reads transcript.txt first. If missing or empty, falls back to
    transcript.clean.json and joins segment texts.

    Returns transcript text or None if not available.
    """
    if not video_id:
        return None

    transcript_dir = TRANSCRIPT_DIR / video_id

    # Step 1: Try transcript.txt
    txt_file = transcript_dir / "transcript.txt"
    if txt_file.exists():
        try:
            text = txt_file.read_text().strip()
            if text:
                return text
        except Exception:
            pass

    # Step 2: Fall back to transcript.clean.json
    json_file = transcript_dir / "transcript.clean.json"
    if json_file.exists():
        try:
            data = json.loads(json_file.read_text())
            if isinstance(data, list):
                # Join each segment's text field with a space
                texts = []
                for segment in data:
                    if isinstance(segment, dict) and segment.get("text"):
                        texts.append(segment["text"])
                if texts:
                    return " ".join(texts).strip()
        except Exception:
            pass

    return None


def load_transcribe_timeline(video_id: str) -> Optional[dict]:
    """
    Load transcript timeline (segments with timing) for a video.

    Reads transcript.clean.json and builds a clean segments list.
    Returns dict with duration, segment_count, and segments.

    Returns None if not available or invalid.
    """
    if not video_id:
        return None

    transcript_dir = TRANSCRIPT_DIR / video_id
    json_file = transcript_dir / "transcript.clean.json"

    if not json_file.exists():
        return None

    try:
        data = json.loads(json_file.read_text())
    except Exception:
        return None

    if not isinstance(data, list):
        return None

    # Build clean segments list
    segments = []
    max_end = 0.0

    for segment in data:
        if not isinstance(segment, dict):
            continue

        text = segment.get("text")
        if not text or not isinstance(text, str) or not text.strip():
            continue

        # Parse timing values
        start_val = segment.get("start")
        end_val = segment.get("end")
        duration_val = segment.get("duration")

        # Convert start to float if possible
        start = None
        if start_val is not None:
            try:
                start = float(start_val)
            except (ValueError, TypeError):
                continue

        # Convert end to float if possible
        end = None
        if end_val is not None:
            try:
                end = float(end_val)
            except (ValueError, TypeError):
                pass

        # Convert duration to float if possible
        duration = None
        if duration_val is not None:
            try:
                duration = float(duration_val)
            except (ValueError, TypeError):
                pass

        # Compute missing values
        if end is None and start is not None and duration is not None:
            end = start + duration
        elif duration is None and start is not None and end is not None:
            duration = end - start

        # Need at least start to be valid
        if start is None:
            continue

        segment_clean = {
            "start": start,
            "end": end if end is not None else start,
            "duration": duration if duration is not None else 0.0,
            "text": text.strip(),
        }

        # Track max end
        if end is not None and end > max_end:
            max_end = end

        segments.append(segment_clean)

    if not segments:
        return None

    return {
        "duration": max_end,
        "segment_count": len(segments),
        "segments": segments,
    }


def validate_step_input(step: str, video_id: str) -> tuple[bool, Optional[str]]:
    """
    Validate that input is ready before running a step.
    Returns (is_ready, error_message).
    """
    run_dir = OUTPUT_DIR / video_id

    if step == "opening":
        # Need valid non-Telegram watermarked video from watermark step.
        watermarked_dir = run_dir / "watermarked"
        if not watermarked_dir.exists():
            return (False, f"watermarked directory does not exist: {watermarked_dir}")

        mp4_files = find_opening_watermarked_inputs(run_dir)
        if not mp4_files:
            return (False, f"No non-Telegram *_wm.mp4 files found in {watermarked_dir}")

        # Check file size stability (wait 2 seconds)
        first_short = mp4_files[0]
        size1 = first_short.stat().st_size
        time.sleep(2)
        size2 = first_short.stat().st_size
        if size1 != size2:
            return (False, "Input short is still being written")

        # Validate the first short
        is_valid, error = validate_mp4_file(first_short)
        if not is_valid:
            return (False, f"Input short invalid: {error}")

        has_audio, audio_error = validate_audio_stream(first_short)
        if not has_audio:
            return (False, f"Input short has no audio stream: {audio_error}")

        return (True, None)

    elif step == "watermark":
        # Need valid shorts from render
        shorts_dir = run_dir / "shorts"
        if not shorts_dir.exists():
            return (False, f"shorts directory does not exist: {shorts_dir}")

        mp4_files = list(shorts_dir.glob("*.mp4"))
        if not mp4_files:
            return (False, f"No MP4 files found in {shorts_dir}")

        # Check file size stability (wait 2 seconds)
        first_short = mp4_files[0]
        size1 = first_short.stat().st_size
        time.sleep(2)
        size2 = first_short.stat().st_size
        if size1 != size2:
            return (False, "Input short is still being written")

        # Validate the first short
        is_valid, error = validate_mp4_file(first_short)
        if not is_valid:
            return (False, f"Input short invalid: {error}")

        has_audio, audio_error = validate_audio_stream(first_short)
        if not has_audio:
            return (False, f"Input short has no audio stream: {audio_error}")

        return (True, None)

    # Other steps - input validation not implemented yet
    return (True, None)


def check_output_exists(video_id: str) -> bool:
    """Check if output files exist for video_id."""
    run_dir = OUTPUT_DIR / video_id
    shorts_dir = run_dir / "shorts"
    watermarked_dir = run_dir / "watermarked"

    # Check shorts dir
    if shorts_dir.exists():
        mp4_files = list(shorts_dir.glob("*.mp4"))
        if mp4_files:
            return True

    # Check watermarked dir
    if watermarked_dir.exists():
        mp4_files = list(watermarked_dir.glob("*.mp4"))
        if mp4_files:
            return True

    return False


def load_loading_state(video_id: str) -> Optional[dict]:
    """Load loading state from run dir."""
    run_dir = OUTPUT_DIR / video_id
    state_file = run_dir / "loading_state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass
    return None


def determine_job_status(
    returncode: int,
    video_id: str,
    stderr: str = ""
) -> tuple[str, Optional[str], Optional[int]]:
    """
    Determine job status based on returncode and actual output.
    Returns tuple of (status, error_message, error_code).

    If output files exist or loading_state shows completed,
    treat as completed even if returncode != 0.
    """
    # Check if output actually exists (more reliable than returncode)
    output_exists = check_output_exists(video_id)
    loading_state = load_loading_state(video_id)
    pipeline_completed = (
        output_exists or
        (loading_state and loading_state.get("state") == "completed")
    )

    if returncode == 0:
        return ("completed", None, None)
    elif pipeline_completed:
        # Override - pipeline actually succeeded despite non-zero exit
        warning = "Pipeline completed but exit code was non-zero"
        if stderr:
            warning += f": {stderr[:200]}"
        return ("completed", warning, None)
    else:
# Use tail of stderr for error (last 4000 chars)
        error_msg = stderr[-4000:] if stderr else "Unknown error"
        return ("failed", error_msg, returncode)


def reconcile_job_status(job_id: str, job: dict) -> dict:
    """
    Reconcile job status with disk metadata, output files, and loading_state.json.
    Returns the updated job dict.

    This ensures that even if in-memory job status is stale (e.g., 'failed'),
    the API will return the real current status based on actual output files.
    """
    # 1. Load disk metadata
    disk_job = load_job_metadata(job_id)

    # 2. Merge: start from job, overlay fields from disk_job
    if disk_job:
        merged = {**job, **disk_job}
    else:
        merged = dict(job)

    # 3. Get video_id
    video_id = merged.get("video_id")
    if not video_id:
        # No video_id, return merged unchanged
        save_job_metadata(job_id, merged)
        jobs[job_id] = merged
        return merged

    # 4. Determine output check method based on job type
    # If job has step field, use step-specific validation
    job_step = merged.get("step")

    if job_step:
        # Step-specific jobs must not be marked completed by polling while
        # their subprocess is still active. This is critical for opening:
        # opening overwrites watermarked/short_*_wm.mp4, so a pre-existing
        # watermark file would otherwise make the opening job look completed.
        if merged.get("status") in {"queued", "running"}:
            output_exists = False
        else:
            output_exists = step_output_exists(job_step, video_id)
        # For step jobs, do NOT use loading_state to force completed
        # loading_state only applies to full pipeline
        loading_completed = False
    else:
        # Full pipeline job - use generic check
        output_exists = check_output_exists(video_id)
        loading_state = load_loading_state(video_id)
        loading_completed = loading_state and loading_state.get("state") == "completed"

# 5. If output exists OR (for full pipeline only) loading completed, set status to completed
    if output_exists or loading_completed:
        merged["status"] = "completed"
        merged.pop("error", None)
        merged.pop("error_code", None)

        # 6. Add optional warning if old return code was non-zero
        if merged.get("returncode") not in (None, 0):
            merged["warning"] = "Pipeline output exists but recorded returncode was non-zero"

    # 7. If job was already marked failed, don't override (preserve failure)
    # unless we found actual output for a step-specific job

    # 8. Downgrade status if artifact is missing for step jobs
    # If job_step exists, output doesn't exist, AND old status was "completed", downgrade to failed
    if job_step and not output_exists and merged.get("status") == "completed":
        # Check if there's an error from watermark_plan.json
        plan_error = None
        if job_step == "watermark":
            plan_error = read_watermark_plan_error(video_id)

        if plan_error:
            merged["status"] = "failed"
            merged["error_code"] = "watermark_failed"
            merged["error"] = plan_error
        else:
            merged["status"] = "failed"
            merged["error_code"] = "missing_expected_artifact"
            # Provide specific error message based on step
            error_messages = {
                "watermark": "Watermark step completed but no watermarked video was created",
                "render": "Render step completed but no short video was created",
                "opening": "Opening step completed but no valid non-Telegram watermarked video was found",
            }
            merged["error"] = error_messages.get(job_step, f"{job_step} step completed but no output was found")

    # 9. Save reconciled metadata
    save_job_metadata(job_id, merged)
    jobs[job_id] = merged

    return merged


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL."""
    url = url.strip()
    # Direct ID
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    # youtu.be
    match = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)
    # youtube.com/watch?v= or youtube.com/shorts/
    match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)
    match = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot extract video ID from: {url}")


def check_command(cmd: str) -> bool:
    """Check if command exists and is executable."""
    result = subprocess.run(
        ["which", cmd],
        capture_output=True,
        text=True
    )
    return result.returncode == 0


def check_command_runs(cmd: list[str]) -> bool:
    """Check if command runs successfully with --version or -version."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def run_background_job(job_id: str, video_id: str, request_data: dict):
    """Run the pipeline in background."""
    try:
        # Build command arguments
        cmd = ["./run.sh", "-o", str(OUTPUT_DIR)]

        if request_data.get("num_clips"):
            cmd.extend(["-n", str(request_data["num_clips"])])
        if request_data.get("quality"):
            cmd.extend(["-q", str(request_data["quality"])])
        if request_data.get("languages"):
            cmd.extend(["-l", str(request_data["languages"])])
        if request_data.get("skip_download"):
            cmd.append("--skip-download")
        if request_data.get("skip_transcript"):
            cmd.append("--skip-transcript")
        if not request_data.get("no_watermark", False):
            if request_data.get("watermark_text"):
                cmd.extend(["--watermark-text", str(request_data["watermark_text"])])
            if request_data.get("watermark_mode"):
                cmd.extend(["--watermark-mode", str(request_data["watermark_mode"])])
            if request_data.get("watermark_position"):
                cmd.extend(["--watermark-position", str(request_data["watermark_position"])])
        else:
            cmd.append("--no-watermark")

        cmd.append(request_data["source"])

# Update job status
        jobs[job_id].update({
            "status": "running",
            "video_id": video_id,
            "command": " ".join(cmd),
            "started_at": datetime.now(timezone.utc).isoformat()
        })
        save_job_metadata(job_id, jobs[job_id])

# Run the command
        result = subprocess.run(
            cmd,
            cwd=str(APP_DIR),
            capture_output=True,
            text=True,
            timeout=7200  # 2 hour timeout
        )

        # Save full logs before determining status
        log_paths = save_job_process_logs(job_id, result.stdout, result.stderr)
        if log_paths:
            jobs[job_id].update(log_paths)

        # Combine stdout and stderr for complete error context
        combined_output = combine_process_output(result.stdout, result.stderr)

        # Determine status based on returncode AND actual output files
        job_status, error_msg, error_code = determine_job_status(
            result.returncode,
            video_id,
            combined_output
        )

        # Update job with determined status
        jobs[job_id].update({
            "status": job_status,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "returncode": result.returncode
        })

        if error_msg:
            jobs[job_id]["error"] = error_msg
        if error_code:
            jobs[job_id]["error_code"] = error_code

    except subprocess.TimeoutExpired as exc:
        # Save any captured stdout/stderr before determining status
        log_paths = save_job_process_logs(job_id, exc.stdout, exc.stderr)
        if log_paths:
            jobs[job_id].update(log_paths)

        # Use tail of combined output if available, otherwise generic message
        combined = combine_process_output(exc.stdout, exc.stderr)
        error_msg = combined[-4000:] if combined else "Command timed out"

        jobs[job_id].update({
            "status": "failed",
            "error": error_msg,
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        jobs[job_id].update({
            "status": "failed",
            "error": str(e)[:500],
            "completed_at": datetime.now(timezone.utc).isoformat()
        })

    # Persist final status
    save_job_metadata(job_id, jobs[job_id])


def run_transcript_job_with_audio_fallback(job_id: str, video_id: str, request_data: dict, cmd: list[str]):
    """Run transcript job with audio fallback on failure.

    This function runs the initial transcript command (./transcribe_youtube.sh).
    If it fails, it falls back to audio transcription using Whisper
    if a downloaded video file can be found.
    """
    job_step = "transcript"
    request_languages = request_data.get("languages", "id,en")

    try:
        # Update job status to running
        jobs[job_id].update({
            "status": "running",
            "video_id": video_id,
            "command": " ".join(cmd),
            "started_at": datetime.now(timezone.utc).isoformat()
        })
        save_job_metadata(job_id, jobs[job_id])

        # Step 1: Run the original transcript command
        result = subprocess.run(
            cmd,
            cwd=str(APP_DIR),
            capture_output=True,
            text=True,
            timeout=7200
        )

        # Save full logs
        log_paths = save_job_process_logs(job_id, result.stdout, result.stderr)
        if log_paths:
            jobs[job_id].update(log_paths)

        # Check if command succeeded and output exists
        if result.returncode == 0 and step_output_exists(job_step, video_id):
            jobs[job_id].update({
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "returncode": result.returncode
            })
            save_job_metadata(job_id, jobs[job_id])
            return  # Success - job is completed

        # Command failed or no output - try audio fallback
        combined = combine_process_output(result.stdout, result.stderr)
        fallback_error = None

        _log_fallback(f"YouTube transcript command failed for {video_id} (exit={result.returncode})")
        _log_fallback(f"  Reason: {combined[:300]}")

        # Try to find downloaded video for fallback
        video_path = find_downloaded_video(video_id)
        if video_path:
            try:
                # Run audio fallback transcription
                _log_fallback(f"Found video file: {video_path.name}, starting Whisper fallback")
                print(f"Transcript command failed, trying audio fallback with {video_path}")
                word_timestamps_path = run_audio_fallback_transcription(
                    video_id=video_id,
                    video_path=video_path,
                    language=request_languages,
                )

                # Convert word timestamps to transcript files
                _log_fallback("Converting word timestamps to transcript files ...")
                convert_word_timestamps_to_transcript_files(
                    video_id=video_id,
                    language=request_languages,
                )
                _log_fallback("Conversion complete")

                # Verify output now exists
                if step_output_exists(job_step, video_id):
                    _log_fallback(f"Transcript output verified for {video_id} — marking job completed")
                    jobs[job_id].update({
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "returncode": 0,
                        "fallback": "audio-whisper-fallback",
                    })
                    save_job_metadata(job_id, jobs[job_id])
                    return  # Fallback success - job is completed
                else:
                    fallback_error = "Audio fallback completed but transcript output not found"
                    _log_fallback(f"WARN: {fallback_error}")

            except Exception as e:
                fallback_error = str(e)[:1000]
                _log_fallback(f"Whisper fallback FAILED: {fallback_error}")
        else:
            _log_fallback(f"No downloaded video found for {video_id} — cannot run audio fallback")

        # Both failed - mark as failed
        error_msg = f"Transcript failed. YouTube transcript: {combined[:500]}"
        if fallback_error:
            error_msg += f" | Audio fallback: {fallback_error}"

        _log_fallback(f"All transcript methods FAILED for {video_id}")
        jobs[job_id].update({
            "status": "failed",
            "error": error_msg,
            "returncode": result.returncode if result.returncode else 1,
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
        save_job_metadata(job_id, jobs[job_id])

    except subprocess.TimeoutExpired as exc:
        log_paths = save_job_process_logs(job_id, exc.stdout, exc.stderr)
        if log_paths:
            jobs[job_id].update(log_paths)

        combined = combine_process_output(exc.stdout, exc.stderr)
        error_msg = f"Transcript command timed out: {combined[-1000:]}"

        _log_fallback(f"YouTube transcript command TIMED OUT for {video_id}")

        # Try audio fallback even after timeout
        video_path = find_downloaded_video(video_id)
        if video_path:
            try:
                _log_fallback(f"Attempting Whisper fallback after timeout with {video_path.name}")
                word_timestamps_path = run_audio_fallback_transcription(
                    video_id=video_id,
                    video_path=video_path,
                    language=request_languages,
                )
                _log_fallback("Converting word timestamps to transcript files ...")
                convert_word_timestamps_to_transcript_files(
                    video_id=video_id,
                    language=request_languages,
                )
                _log_fallback("Conversion complete")

                if step_output_exists(job_step, video_id):
                    _log_fallback(f"Transcript output verified for {video_id} after timeout fallback — completed")
                    jobs[job_id].update({
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "fallback": "audio-whisper-fallback",
                    })
                    save_job_metadata(job_id, jobs[job_id])
                    return

            except Exception as fallback_e:
                _log_fallback(f"Whisper fallback after timeout FAILED: {str(fallback_e)[:500]}")
                error_msg += f" | Fallback also failed: {str(fallback_e)[:500]}"
        else:
            _log_fallback(f"No downloaded video found for {video_id} — cannot run audio fallback after timeout")

        _log_fallback(f"All transcript methods FAILED for {video_id} (timeout path)")
        jobs[job_id].update({
            "status": "failed",
            "error": error_msg,
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
        save_job_metadata(job_id, jobs[job_id])

    except Exception as e:
        _log_fallback(f"Unexpected error in transcript job for {video_id}: {str(e)[:300]}")
        jobs[job_id].update({
            "status": "failed",
            "error": str(e)[:500],
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
        save_job_metadata(job_id, jobs[job_id])


def run_command_job(job_id: str, video_id: str, cmd: list[str]):
    """Run a single pipeline step command in background."""
    # Get step from job if already created
    job_step = jobs[job_id].get("step") if job_id in jobs else None

    # Part 4: Check if this is a render job with payload
    request_data = jobs[job_id].get("request", {}) if job_id in jobs else {}
    render_payload = request_data.get("render_payload")

    try:
        jobs[job_id].update({
            "status": "running",
            "video_id": video_id,
            "command": " ".join(cmd),
            "started_at": datetime.now(timezone.utc).isoformat()
        })
        save_job_metadata(job_id, jobs[job_id])

        if job_step == "opening":
            stale_result = OUTPUT_DIR / video_id / "result.json"
            if stale_result.exists():
                stale_result.unlink()
            # Rebuild result.json before opening runs so narrator can access render_payload
            ensure_result_json_for_render_payload(video_id, request_data)

        result = subprocess.run(
            cmd,
            cwd=str(APP_DIR),
            capture_output=True,
            text=True,
            timeout=7200
        )

        # Save full logs
        log_paths = save_job_process_logs(job_id, result.stdout, result.stderr)
        if log_paths:
            jobs[job_id].update(log_paths)

        # After command completes, verify expected output exists
        if result.returncode == 0:
            # Command succeeded, but verify expected artifact exists
            if job_step:
                # Step-specific validation
                if step_output_exists(job_step, video_id):
                    jobs[job_id].update({
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "returncode": result.returncode
                    })
                else:
                    # Command succeeded but no expected output
                    jobs[job_id].update({
                        "status": "failed",
                        "error": f"Command succeeded but no {job_step} output found",
                        "error_code": "missing_expected_artifact",
                        "returncode": result.returncode,
                        "completed_at": datetime.now(timezone.utc).isoformat()
                    })
            else:
                # No step - use generic check
                jobs[job_id].update({
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "returncode": result.returncode
                })
        else:
            # Use tail of combined stdout/stderr for error (last 4000 chars)
            combined = combine_process_output(result.stdout, result.stderr)
            error_msg = combined[-4000:] if combined else "Unknown error"
            jobs[job_id].update({
                "status": "failed",
                "error": error_msg,
                "returncode": result.returncode,
                "completed_at": datetime.now(timezone.utc).isoformat()
            })

    except subprocess.TimeoutExpired as exc:
        # Handle TimeoutExpired - save any captured stdout/stderr
        log_paths = save_job_process_logs(job_id, exc.stdout, exc.stderr)
        if log_paths:
            jobs[job_id].update(log_paths)

        combined = combine_process_output(exc.stdout, exc.stderr)
        error_msg = combined[-4000:] if combined else "Command timed out"

        jobs[job_id].update({
            "status": "failed",
            "error": error_msg,
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        jobs[job_id].update({
            "status": "failed",
            "error": str(e)[:500],
            "completed_at": datetime.now(timezone.utc).isoformat()
        })

# Part 4: Save render_payload.json after render completes (safety net)
    if job_step == "render" and render_payload and jobs[job_id].get("status") == "completed":
        try:
            save_render_payload_file(video_id, render_payload)
        except Exception as e:
            print(f"WARNING: Failed to save render_payload.json after render: {e}", file=sys.stderr)

    save_job_metadata(job_id, jobs[job_id])


def create_step_job(
    *,
    step: str,
    request_data: dict,
    background_tasks: BackgroundTasks,
    cmd: list[str],
    video_id: str,
) -> dict:
    """Create and enqueue a single-step job."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "video_id": video_id,
        "status": "queued",
        "step": step,
        "request": request_data,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    save_job_metadata(job_id, jobs[job_id])
    background_tasks.add_task(run_command_job, job_id, video_id, cmd)
    return {
        "job_id": job_id,
        "step": step,
        "status_url": f"/jobs/{job_id}",
        "result_url": f"/jobs/{job_id}/result"
    }


# Request models
class GenerateRequest(BaseModel):
    source: str
    num_clips: Optional[int] = 3
    quality: Optional[str] = "1080"
    languages: Optional[str] = "id,en"
    skip_download: Optional[bool] = False
    skip_transcript: Optional[bool] = False
    no_watermark: Optional[bool] = False
    watermark_text: Optional[str] = "@KilasanVideo"
    watermark_mode: Optional[str] = "text"
    watermark_position: Optional[str] = "center_15_top"
    opening_statement: Optional[str] = ""
    opening_image: Optional[str] = ""
    opening_voice: Optional[str] = "id-ID-GadisNeural"
    opening_rate: Optional[str] = "+10%"
    opening_pitch: Optional[str] = "+0Hz"
    opening_thumbnail_title: Optional[str] = ""
    opening_thumbnail_talents: Optional[str] = ""
    opening_thumbnail_font: Optional[str] = ""
    opening_upload_title: Optional[str] = ""
    opening_source_title: Optional[str] = ""
    opening_bgm: Optional[str] = ""
    opening_bgm_volume: Optional[float] = 0.30


class StepRequest(GenerateRequest):
    render_payload: Optional[dict] = None


class CleanupVideoRequest(BaseModel):
    video_id: str
    delete_assets: Optional[bool] = True
    delete_artifacts: Optional[bool] = True
    delete_jobs: Optional[bool] = True
    delete_source_video: Optional[bool] = False
    delete_transcripts: Optional[bool] = False


def validate_cleanup_video_id(video_id: str) -> str:
    """Validate a YouTube video id before using it for cleanup paths."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise HTTPException(status_code=400, detail="Invalid video_id")
    return video_id


def is_path_inside(child: Path, parent: Path) -> bool:
    """Return true when child resolves under parent."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def delete_storage_path(path: Path, deleted_paths: list[str], skipped_paths: list[dict]) -> None:
    """Delete only paths inside STORAGE_DIR and record the outcome."""
    resolved = path.resolve()
    storage_root = STORAGE_DIR.resolve()

    if resolved == storage_root or not is_path_inside(resolved, storage_root):
        skipped_paths.append({
            "path": str(path),
            "reason": "outside_storage_or_storage_root"
        })
        return

    if not resolved.exists():
        skipped_paths.append({
            "path": str(path),
            "reason": "not_found"
        })
        return

    try:
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        deleted_paths.append(str(resolved.relative_to(storage_root)))
    except Exception as exc:
        skipped_paths.append({
            "path": str(path),
            "reason": f"delete_failed: {exc}"
        })


def json_file_mentions_video_id(path: Path, video_id: str) -> bool:
    """Check whether a JSON file contains the video id anywhere in its data."""
    try:
        data = json.loads(path.read_text())
    except Exception:
        return False
    return video_id in json.dumps(data, ensure_ascii=False)


def save_render_payload_file(video_id: str, payload: dict) -> Optional[Path]:
    """
    Save render_payload.json to disk.

    Returns the Path of the written file, or None if video_id or payload is empty.
    Raises exceptions on write failure (propagates to caller).
    """
    if not video_id:
        return None
    if not payload:
        return None

    run_dir = OUTPUT_DIR / video_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload_file = run_dir / "render_payload.json"
    payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload_file


def ensure_result_json_for_render_payload(video_id: str, request_data: dict) -> bool:
    """
    Ensure result.json exists with highlight data from render_payload before opening step runs.

    The opening narrator script (_read_highlights) expects result.json with a 'highlights'
    array containing clip timing info (start, end). This function rebuilds result.json
    from render_payload if available.

    Args:
        video_id: The YouTube video ID
        request_data: The job's request data containing render_payload

    Returns:
        True if result.json was created/updated, False if nothing was done
    """
    run_dir = OUTPUT_DIR / video_id
    result_json_path = run_dir / "result.json"

    # Get render_payload from request_data
    render_payload = request_data.get("render_payload") if request_data else None
    if not render_payload:
        return False

    # Extract timing info from render_payload
    try:
        start = float(render_payload.get("start", 0))
        end = float(render_payload.get("end", 0))
    except (TypeError, ValueError):
        return False

    if end <= start:
        return False

    # Build highlight entry from render_payload
    highlight = {
        "start": start,
        "end": end,
        "duration": round(end - start, 3),
    }

    # Preserve optional fields from render_payload
    for field in ["clip_index", "viral_score", "clip_type", "structure", "why_this_clip_works"]:
        if field in render_payload:
            highlight[field] = render_payload[field]

    # Build result.json structure
    result_data = {
        "highlights": [highlight],
        "shorts": [highlight],  # Also include in shorts for compatibility
    }

    # If result.json already exists, try to preserve existing highlights and merge
    if result_json_path.exists():
        try:
            existing_data = json.loads(result_json_path.read_text())
            # Preserve existing highlights if they exist and are valid
            existing_highlights = existing_data.get("highlights", [])
            if isinstance(existing_highlights, list) and existing_highlights:
                result_data["highlights"] = existing_highlights
            # Preserve shorts if they exist
            existing_shorts = existing_data.get("shorts", [])
            if isinstance(existing_shorts, list) and existing_shorts:
                result_data["shorts"] = existing_shorts
        except Exception:
            pass  # Use our built data

    # Write result.json
    run_dir.mkdir(parents=True, exist_ok=True)
    result_json_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2))
    return True


def normalize_render_payload(payload: Optional[dict]) -> Optional[dict]:
    """
    Normalize and validate render_payload.

    Returns None if payload is None.
    Otherwise validates and returns normalized dict with:
    - start: float
    - end: float
    - duration: computed as end - start
    - Preserved optional fields

    Raises ValueError if validation fails.
    """
    if payload is None:
        return None

    # Require start
    if "start" not in payload:
        raise ValueError("render_payload requires 'start' field")

    # Require end
    if "end" not in payload:
        raise ValueError("render_payload requires 'end' field")

    # Convert to float
    try:
        start = float(payload["start"])
    except (ValueError, TypeError) as e:
        raise ValueError(f"render_payload 'start' must be numeric: {e}")

    try:
        end = float(payload["end"])
    except (ValueError, TypeError) as e:
        raise ValueError(f"render_payload 'end' must be numeric: {e}")

    # Reject if end <= start
    if end <= start:
        raise ValueError(f"render_payload 'end' must be greater than 'start': {end} <= {start}")

    # Compute canonical duration
    duration = round(end - start, 3)

    # Build normalized result with required fields
    normalized = {
        "start": start,
        "end": end,
        "duration": duration,
    }

    # Preserve optional fields
    optional_fields = [
        "clip_index",
        "viral_score",
        "clip_type",
        "hook_3_5_seconds",
        "selected_transcript",
        "structure",
        "why_this_clip_works",
        "youtube_metadata",
        "subtitle_recommendation",
        "editing_recommendation",
        "best_cut_note",
    ]

    for field in optional_fields:
        if field in payload:
            normalized[field] = payload[field]

    return normalized


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "ok": True,
        "ffmpeg": check_command_runs(["ffmpeg", "-version"]),
        "yt_dlp": check_command_runs(["yt-dlp", "--version"]),
        "app_dir": str(APP_DIR),
        "storage_dir": str(STORAGE_DIR),
        "output_dir": str(OUTPUT_DIR),
        "base_url": CONTENT_SHORT_BASE_URL
    }


@app.post("/jobs/generate")
async def create_generate_job(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token)
):
    """Create a new generate job."""
    # Extract video ID
    try:
        video_id = extract_video_id(request.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Generate job ID
    job_id = str(uuid.uuid4())

    # Create job record
    jobs[job_id] = {
        "job_id": job_id,
        "video_id": video_id,
        "status": "queued",
        "request": request.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    # Save to disk
    save_job_metadata(job_id, jobs[job_id])

    # Run in background
    background_tasks.add_task(
        run_background_job,
        job_id,
        video_id,
        request.model_dump()
    )

    return {
        "job_id": job_id,
        "status_url": f"/jobs/{job_id}",
        "result_url": f"/jobs/{job_id}/result"
    }


@app.post("/jobs/steps/transcript")
async def create_transcript_job(
    request: StepRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token)
):
    """Extract or refresh YouTube transcript only.

    This endpoint tries YouTube transcript first. If it fails,
    it falls back to audio transcription using Whisper.
    """
    try:
        video_id = extract_video_id(request.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cmd = [
        "./transcribe_youtube.sh",
        "-o", str(TRANSCRIPT_DIR),
        "-l", str(request.languages),
        request.source,
    ]

    # Use the new function with audio fallback for transcript jobs
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "video_id": video_id,
        "status": "queued",
        "step": "transcript",
        "request": request.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    save_job_metadata(job_id, jobs[job_id])
    background_tasks.add_task(
        run_transcript_job_with_audio_fallback,
        job_id,
        video_id,
        request.model_dump(),
        cmd,
    )
    return {
        "job_id": job_id,
        "step": "transcript",
        "status_url": f"/jobs/{job_id}",
        "result_url": f"/jobs/{job_id}/result"
    }


@app.post("/jobs/steps/download")
async def create_download_job(
    request: StepRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token)
):
    """Download source YouTube video only."""
    try:
        video_id = extract_video_id(request.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cmd = [
        "./download_youtube_hd.sh",
        "-q", str(request.quality),
        "-o", str(VIDEO_DIR),
        request.source,
    ]
    return create_step_job(
        step="download",
        request_data=request.model_dump(),
        background_tasks=background_tasks,
        cmd=cmd,
        video_id=video_id,
    )


@app.post("/jobs/cleanup/video")
async def cleanup_video_artifacts(
    request: CleanupVideoRequest,
    token: str = Depends(verify_token)
):
    """Delete stale assets, artifacts, and job records for a video."""
    video_id = validate_cleanup_video_id(request.video_id)
    deleted_paths: list[str] = []
    skipped_paths: list[dict] = []
    deleted_jobs: list[str] = []
    deleted_subtitle_jobs: list[str] = []

    if request.delete_assets:
        delete_storage_path(OUTPUT_DIR / video_id, deleted_paths, skipped_paths)

    if request.delete_source_video:
        for source_file in VIDEO_DIR.glob(f"*{video_id}*"):
            delete_storage_path(source_file, deleted_paths, skipped_paths)

    if request.delete_transcripts:
        delete_storage_path(TRANSCRIPT_DIR / video_id, deleted_paths, skipped_paths)

    if request.delete_jobs:
        for job_id, job in list(jobs.items()):
            if job.get("video_id") == video_id or video_id in json.dumps(job, ensure_ascii=False):
                jobs.pop(job_id, None)
                deleted_jobs.append(job_id)

        for metadata_file in API_JOBS_DIR.glob("*.json"):
            if not json_file_mentions_video_id(metadata_file, video_id):
                continue

            job_id = metadata_file.stem
            for job_file in API_JOBS_DIR.glob(f"{job_id}*"):
                delete_storage_path(job_file, deleted_paths, skipped_paths)
            if job_id not in deleted_jobs:
                deleted_jobs.append(job_id)

        subtitle_jobs_dir = subtitle_settings.subtitle_output_dir
        if subtitle_jobs_dir.exists():
            for subtitle_job_dir in subtitle_jobs_dir.iterdir():
                if not subtitle_job_dir.is_dir():
                    continue

                input_file = subtitle_job_dir / "input.json"
                result_file = subtitle_job_dir / "result.json"
                if (
                    json_file_mentions_video_id(input_file, video_id)
                    or json_file_mentions_video_id(result_file, video_id)
                ):
                    delete_storage_path(subtitle_job_dir, deleted_paths, skipped_paths)
                    deleted_subtitle_jobs.append(subtitle_job_dir.name)

    if request.delete_artifacts and not request.delete_assets:
        skipped_paths.append({
            "path": str(OUTPUT_DIR / video_id),
            "reason": "delete_artifacts_requires_delete_assets_for_video_scoped_artifacts"
        })

    return {
        "status": "completed",
        "video_id": video_id,
        "deleted_paths": deleted_paths,
        "deleted_jobs": deleted_jobs,
        "deleted_subtitle_jobs": deleted_subtitle_jobs,
        "skipped_paths": skipped_paths,
    }


@app.post("/jobs/steps/analyze")
async def create_analyze_job(
    request: StepRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token)
):
    """Analyze transcript into viral moments without rendering video."""
    try:
        video_id = extract_video_id(request.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cmd = [
        "./run.sh",
        "-o", str(OUTPUT_DIR),
        "-n", str(request.num_clips),
        "-q", str(request.quality),
        "-l", str(request.languages),
        "--skip-download",
        "--skip-transcript",
        "--skip-render",
        request.source,
    ]
    return create_step_job(
        step="analyze",
        request_data=request.model_dump(),
        background_tasks=background_tasks,
        cmd=cmd,
        video_id=video_id,
    )


@app.post("/jobs/steps/render")
async def create_render_job(
    request: StepRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token)
):
    """Render shorts without applying watermark."""
    try:
        video_id = extract_video_id(request.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Part 3: Normalize and validate render_payload
    normalized_payload = None
    if request.render_payload:
        try:
            normalized_payload = normalize_render_payload(request.render_payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Part 2: Save payload when render job is created (before calling create_step_job)
    render_payload_path = None
    if normalized_payload:
        try:
            render_payload_path = save_render_payload_file(video_id, normalized_payload)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save render_payload.json: {e}")

    # Part 3: Build command - use payload time range if available
    if normalized_payload:
        # Force num_clips = 1 when payload is provided
        num_clips = 1
        cmd = [
            "./run.sh",
            "-o", str(OUTPUT_DIR),
            "-n", str(num_clips),
            "-q", str(request.quality),
            "-l", str(request.languages),
            "--crop-start", str(normalized_payload["start"]),
            "--crop-end", str(normalized_payload["end"]),
            "--skip-download",
            "--skip-transcript",
            "--no-watermark",
            request.source,
        ]
    else:
        # Part 3: Keep current behavior when no payload
        cmd = [
            "./run.sh",
            "-o", str(OUTPUT_DIR),
            "-n", str(request.num_clips),
            "-q", str(request.quality),
            "-l", str(request.languages),
            "--skip-download",
            "--skip-transcript",
            "--no-watermark",
            request.source,
        ]

    # Part 4: Include normalized payload in request_data
    request_data = request.model_dump()
    if normalized_payload:
        request_data["render_payload"] = normalized_payload

    # Part 3: Store payload path in job metadata
    if render_payload_path:
        request_data["render_payload_path"] = str(render_payload_path.relative_to(STORAGE_DIR))

    result = create_step_job(
        step="render",
        request_data=request_data,
        background_tasks=background_tasks,
        cmd=cmd,
        video_id=video_id,
    )

    # Part 6: Add optional payload summary to response
    if normalized_payload:
        result["render_payload"] = {
            "start": normalized_payload["start"],
            "end": normalized_payload["end"],
            "duration": normalized_payload["duration"],
        }

    return result


@app.post("/jobs/steps/opening")
async def create_opening_job(
    request: StepRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token)
):
    """Prepend opening narration to non-Telegram watermarked videos."""
    try:
        video_id = extract_video_id(request.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    narration_text = (request.opening_statement or "").strip()
    if not narration_text:
        raise HTTPException(status_code=400, detail="opening_statement is required")

    # Validate input is ready before running step
    is_ready, error_msg = validate_step_input("opening", video_id)
    if not is_ready:
        raise HTTPException(
            status_code=400,
            detail=f"Input watermarked video is not ready or invalid: {error_msg}"
        )

    # 1. Resolve static thumbnail asset
    thumbnail_path = find_static_opening_thumbnail(video_id)
    if not thumbnail_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "Opening thumbnail asset not found. "
                f"Expected assets/thumbnail/{video_id}.png|jpg|jpeg|webp"
            ),
        )

    run_dir = OUTPUT_DIR / video_id
    cmd = [
        CV_PYTHON_BIN,
        "scripts/opening_narrator.py",
        str(run_dir),
        "--text", narration_text,
        "--voice", str(request.opening_voice or "id-ID-GadisNeural"),
        "--rate", str(request.opening_rate or "+10%"),
        "--pitch", str(request.opening_pitch or "+0Hz"),
        "--image", str(thumbnail_path), # 2. ALWAYS send the found static thumbnail
    ]

    # Legacy payload fields are ignored for thumbnail generation:
    # opening_thumbnail_title, opening_thumbnail_talents, opening_thumbnail_font
    # opening_upload_title, opening_source_title

    if request.opening_bgm:
        cmd.extend(["--bgm", str(request.opening_bgm)])
    if request.opening_bgm_volume is not None:
        cmd.extend(["--bgm-volume", str(request.opening_bgm_volume)])

    return create_step_job(
        step="opening",
        request_data=request.model_dump(),
        background_tasks=background_tasks,
        cmd=cmd,
        video_id=video_id,
    )


@app.post("/jobs/steps/watermark")
async def create_watermark_job(
    request: StepRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token)
):
    """Apply watermark to already rendered shorts."""
    try:
        video_id = extract_video_id(request.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    active_opening_jobs = find_active_step_jobs(video_id, "opening")
    if active_opening_jobs:
        active_job_ids = ", ".join(
            str(job.get("job_id", "unknown")) for job in active_opening_jobs
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Opening step is still running for this video. "
                f"Wait until it completes before watermark. active_opening_jobs={active_job_ids}"
            )
        )

    # Validate input is ready before running step
    is_ready, error_msg = validate_step_input("watermark", video_id)
    if not is_ready:
        raise HTTPException(
            status_code=400,
            detail=f"Input short is not ready or invalid: {error_msg}"
        )

    cmd = ["./watermark_shorts.sh", "-o", str(OUTPUT_DIR)]
    if request.watermark_text:
        cmd.extend(["--text", str(request.watermark_text)])
    if request.watermark_mode:
        cmd.extend(["--mode", str(request.watermark_mode)])
    if request.watermark_position:
        cmd.extend(["--position", str(request.watermark_position)])
    cmd.append(video_id)

    return create_step_job(
        step="watermark",
        request_data=request.model_dump(),
        background_tasks=background_tasks,
        cmd=cmd,
        video_id=video_id,
    )


@app.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    token: str = Depends(verify_token)
):
    """Get job status."""
    # Check memory first
    if job_id in jobs:
        job = jobs[job_id]
    else:
        # Try loading from disk
        metadata = load_job_metadata(job_id)
        if metadata is None:
            raise HTTPException(status_code=404, detail="Job not found")
        jobs[job_id] = metadata
        job = metadata

# Reconcile job status with actual output files
    job = reconcile_job_status(job_id, job)
    video_id = job.get("video_id")

    response = {
        "job_id": job["job_id"],
        "status": job["status"],
        "video_id": video_id,
    }

    # Include error if job failed
    if job["status"] == "failed":
        response["error"] = job.get("error", "Unknown error")

    # Add transcribe field for transcript jobs
    if job.get("step") == "transcript":
        response["transcribe"] = load_transcribe_text(video_id) if video_id else None
        response["transcribe_timeline"] = load_transcribe_timeline(video_id) if video_id else None

    # Include loading state if exists
    if video_id:
        loading_state_file = OUTPUT_DIR / video_id / "loading_state.json"
        if loading_state_file.exists():
            try:
                loading_state = json.loads(loading_state_file.read_text())
                # If job failed, sync loading_state to reflect failure
                if job["status"] == "failed" and loading_state.get("state") == "running":
                    loading_state["state"] = "failed"
                    loading_state["progress"] = 0.0
                    loading_state["label"] = "Failed"
                    loading_state["detail"] = job.get("error", "Pipeline failed")
                    loading_state["updated_at"] = datetime.now(timezone.utc).isoformat()
                    # Update the file to keep it in sync
                    try:
                        loading_state_file.write_text(json.dumps(loading_state, ensure_ascii=False, indent=2))
                    except Exception:
                        pass
                response["loading_state"] = loading_state
            except Exception:
                pass

    return response


@app.get("/jobs/{job_id}/result")
async def get_job_result(
    job_id: str,
    token: str = Depends(verify_token)
):
    """Get job result metadata."""
    # Check memory first
    if job_id in jobs:
        job = jobs[job_id]
    else:
        # Try loading from disk
        metadata = load_job_metadata(job_id)
        if metadata is None:
            raise HTTPException(status_code=404, detail="Job not found")
        jobs[job_id] = metadata
        job = metadata

    # Reconcile job status with actual output files
    job = reconcile_job_status(job_id, job)

    video_id = job.get("video_id")

    if not video_id:
        raise HTTPException(status_code=404, detail="Video ID not found")

    run_dir = OUTPUT_DIR / video_id
    result_file = run_dir / "result.json"

    if not result_file.exists():
        return {
            "job_id": job_id,
            "status": job.get("status", "unknown"),
            "message": "Result not ready"
        }

    # Load result
    result = json.loads(result_file.read_text())

    # Build base URL for download links
    base_url = CONTENT_SHORT_BASE_URL.rstrip("/")

# Find output files
    output_files = []
    job_step = job.get("step")

    # Check watermarked dir
    watermarked_dir = run_dir / "watermarked"
    if watermarked_dir.exists():
        for f in sorted(watermarked_dir.glob("*.mp4")):
            if job_step == "opening" and not is_opening_watermarked_input(f):
                continue
            output_files.append({
                "filename": f.name,
                "path": str(f.relative_to(STORAGE_DIR)),
                "url": f"/jobs/{job_id}/files/{f.name}",
                "download_url": f"{base_url}/jobs/{job_id}/files/{f.name}",
                "size": f.stat().st_size
            })

    # Check shorts dir, but not for steps whose final artifact lives in watermarked/.
    if job_step not in ("watermark", "opening"):
        shorts_dir = run_dir / "shorts"
        if shorts_dir.exists():
            for f in sorted(shorts_dir.glob("*.mp4")):
                if f.name not in [of["filename"] for of in output_files]:
                    output_files.append({
                        "filename": f.name,
                        "path": str(f.relative_to(STORAGE_DIR)),
                        "url": f"/jobs/{job_id}/files/{f.name}",
                        "download_url": f"{base_url}/jobs/{job_id}/files/{f.name}",
                        "size": f.stat().st_size
                    })

# Get actual job status (not hardcoded)
    job_status = job.get("status", "unknown")

# Build response with proper status propagation
    response = {
        "job_id": job_id,
        "status": job_status,
        "video_id": video_id,
        "success": job_status == "completed",
        "result": result,
        "files": output_files
    }

    # Get step if this is a step-specific job (needed for artifact_status)
    job_step = job.get("step")

    # Include artifact status debug info
    if job_step:
        # Count different artifact types. Telegram delivery files are secondary artifacts.
        watermarked_count = len([
            f for f in output_files
            if f["filename"].endswith("_wm.mp4") and "_telegram" not in f["filename"]
        ])
        telegram_count = len([f for f in output_files if "_telegram" in f["filename"]])
        shorts_count = len([
            f for f in output_files
            if not f["filename"].endswith("_wm.mp4") and "_telegram" not in f["filename"]
        ])

        response["artifact_status"] = {
            "step": job_step,
            "shorts_count": shorts_count,
            "watermarked_count": watermarked_count,
            "telegram_count": telegram_count,
            "missing_expected_artifact": (
                (job_step in ("watermark", "opening") and watermarked_count == 0) or
                (job_step == "render" and shorts_count == 0)
            )
        }

    # Include error info if job failed
    if job_status == "failed":
        response["error"] = job.get("error", "Unknown error")
        response["error_code"] = job.get("error_code", "RENDER_FAILED")
        response["error_step"] = job.get("error_step")

    return response


@app.get("/jobs/{job_id}/files/{filename}")
async def download_file(
    job_id: str,
    filename: str
):
    """Download a rendered video file."""
    # Prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Find job video_id from memory or disk
    video_id = None
    if job_id in jobs:
        video_id = jobs[job_id].get("video_id")
    else:
        metadata = load_job_metadata(job_id)
        if metadata is not None:
            video_id = metadata.get("video_id")

    if not video_id:
        raise HTTPException(status_code=404, detail="Job not found")

    run_dir = OUTPUT_DIR / video_id

    # Check both shorts and watermarked directories
    search_dirs = [
        run_dir / "watermarked",
        run_dir / "shorts"
    ]

    file_path = None
    for search_dir in search_dirs:
        candidate = search_dir / filename
        if candidate.exists() and candidate.is_file():
            file_path = candidate
            break

    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename=filename
    )


@app.get("/transcripts/{video_id}")
async def get_transcript_metadata(
    video_id: str,
    token: str = Depends(verify_token)
):
    """Get available transcript files for a video."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID")

    transcript_dir = TRANSCRIPT_DIR / video_id
    if not transcript_dir.exists() or not transcript_dir.is_dir():
        raise HTTPException(status_code=404, detail="Transcript not found")

    base_url = CONTENT_SHORT_BASE_URL.rstrip("/")
    files = []
    for path in sorted(transcript_dir.iterdir()):
        if path.is_file():
            files.append({
                "filename": path.name,
                "path": str(path.relative_to(STORAGE_DIR)),
                "url": f"/transcripts/{video_id}/files/{path.name}",
                "download_url": f"{base_url}/transcripts/{video_id}/files/{path.name}",
                "size": path.stat().st_size,
            })

    return {
        "video_id": video_id,
        "files": files,
    }


@app.get("/transcripts/{video_id}/files/{filename}")
async def download_transcript_file(
    video_id: str,
    filename: str,
    token: str = Depends(verify_token)
):
    """Download a transcript file."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    transcript_dir = TRANSCRIPT_DIR / video_id
    file_path = transcript_dir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Transcript file not found")

    media_type = "application/octet-stream"
    if filename.endswith(".json"):
        media_type = "application/json"
    elif filename.endswith((".txt", ".srt", ".vtt")):
        media_type = "text/plain; charset=utf-8"

    return FileResponse(
        file_path,
        media_type=media_type,
        filename=filename,
    )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Content Short API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# Google Drive upload helper
def upload_to_drive(file_path: str, folder_id: str = None) -> dict:
    """
    Upload a file to Google Drive.
    Returns dict with web_view_url and file_id.
    """
    import io
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    # Use token.json for credentials (same as YouTube upload)
    # Check local directory first, then fallback to download-clip
    token_candidates = [
        Path(APP_DIR) / "token.json",
        Path(APP_DIR).parent / "n8n/download-clip/token.json",
        Path("/Users/agusrachman/Documents/Docker/n8n/download-clip/token.json"),
    ]
    token_path = None
    for candidate in token_candidates:
        if candidate.exists():
            token_path = candidate
            break

    if not token_path:
        raise HTTPException(status_code=400, detail=f"token.json not found. Checked: {token_candidates}")

    creds_data = json.loads(token_path.read_text())
    creds = Credentials(
        token=creds_data.get("token"),
        refresh_token=creds_data.get("refresh_token"),
        token_uri=creds_data.get("token_uri"),
        client_id=creds_data.get("client_id"),
        client_secret=creds_data.get("client_secret"),
        scopes=creds_data.get("scopes", ["https://www.googleapis.com/auth/drive.file"]),
    )

    # Refresh if needed
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        # Save updated token
        creds_data["token"] = creds.token
        creds_data["refresh_token"] = creds.refresh_token
        token_path.write_text(json.dumps(creds_data, indent=2))

    service = build("drive", "v3", credentials=creds)

    file_metadata = {"name": Path(file_path).name}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaFileUpload(
        file_path,
        mimetype="video/mp4",
        resumable=True,
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id,webViewLink",
    ).execute()

    # Make file publicly accessible (optional)
    if folder_id != "shared":
        try:
            service.permissions().create(
                fileId=file["id"],
                body={"type": "anyone", "role": "reader"},
            ).execute()
        except Exception:
            pass

    return {
        "file_id": file["id"],
        "web_view_url": file.get("webViewLink", f"https://drive.google.com/file/d/{file['id']}/view"),
    }


@app.post("/jobs/{job_id}/upload/drive")
async def upload_job_to_drive(
    job_id: str,
    folder_id: str = None,
    filename: str = "short_01_wm.mp4",
    token: str = Depends(verify_token)
):
    """Upload a rendered video file to Google Drive."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        # Load job metadata
        job = load_job_metadata(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        video_id = job.get("video_id")
        if not video_id:
            raise HTTPException(status_code=400, detail="Video ID not found")

        run_dir = OUTPUT_DIR / video_id
        logger.info(f"Looking for file in: {run_dir}")

        # Find the file (check watermarked dir first)
        file_path = None
        for search_dir in [run_dir / "watermarked", run_dir / "shorts"]:
            if search_dir.exists():
                candidate = search_dir / filename
                if candidate.exists():
                    file_path = candidate
                    logger.info(f"Found file: {file_path}")
                    break

        if not file_path:
            raise HTTPException(status_code=404, detail=f"File not found: {filename}")

        # Upload to Drive
        result = upload_to_drive(str(file_path), folder_id)

        return {
            "job_id": job_id,
            "video_id": video_id,
            "filename": file_path.name,
            "file_id": result["file_id"],
            "web_view_url": result["web_view_url"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Standalone Google Drive upload endpoint
UPLOAD_TEMP_DIR = Path("/tmp/content-short-uploads")
UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/upload/drive")
async def upload_video_to_drive(
    file: UploadFile = File(..., description="Video file to upload (MP4)"),
    folder_id: str = None,
    token: str = Depends(verify_token)
):
    """
    Upload a video file directly to Google Drive.

    Accepts multipart/form-data with a video file.
    Optional folder_id to specify destination folder.
    Returns file_id and web_view_url.
    """
    import logging
    import tempfile
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    logger = logging.getLogger(__name__)

    # Validate file type
    if not file.filename.lower().endswith((".mp4", ".mkv", ".webm", ".mov")):
        raise HTTPException(
            status_code=400,
            detail="Only video files (mp4, mkv, webm, mov) are supported"
        )

    # Save uploaded file to temp location
    temp_path = UPLOAD_TEMP_DIR / f"{uuid.uuid4()}_{file.filename}"
    try:
        content = await file.read()
        temp_path.write_bytes(content)

        # Check file size
        file_size = temp_path.stat().st_size
        if file_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        logger.info(f"Uploaded temp file: {temp_path} ({file_size} bytes)")

        # Get credentials
        token_candidates = [
            Path(APP_DIR) / "token.json",
            Path(APP_DIR).parent / "n8n/download-clip/token.json",
            Path("/Users/agusrachman/Documents/Docker/n8n/download-clip/token.json"),
        ]
        token_path = None
        for candidate in token_candidates:
            if candidate.exists():
                token_path = candidate
                break

        if not token_path:
            raise HTTPException(
                status_code=400,
                detail=f"token.json not found. Checked: {token_candidates}"
            )

        creds_data = json.loads(token_path.read_text())
        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri"),
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
            scopes=creds_data.get("scopes", ["https://www.googleapis.com/auth/drive.file"]),
        )

        # Refresh if needed
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            creds_data["token"] = creds.token
            creds_data["refresh_token"] = creds.refresh_token
            token_path.write_text(json.dumps(creds_data, indent=2))

        # Build Drive service and upload
        service = build("drive", "v3", credentials=creds)

        file_metadata = {"name": file.filename}
        if folder_id:
            file_metadata["parents"] = [folder_id]

        media = MediaFileUpload(
            str(temp_path),
            mimetype="video/mp4",
            resumable=True,
        )

        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id,webViewLink,name",
        ).execute()

        logger.info(f"Uploaded to Drive: {uploaded_file.get('name')} (ID: {uploaded_file.get('id')})")

        return {
            "filename": uploaded_file.get("name"),
            "file_id": uploaded_file.get("id"),
            "web_view_url": uploaded_file.get(
                "webViewLink",
                f"https://drive.google.com/file/d/{uploaded_file.get('id')}/view"
            ),
            "size": file_size,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp file
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
