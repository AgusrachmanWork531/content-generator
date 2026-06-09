"""
Subtitle Service API Routes.

FastAPI routes for subtitle generation.
Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.

API Endpoints:
1. POST /subtitle/generate - Generate subtitle only
2. POST /subtitle/burn - Generate subtitle + burn video
3. GET /subtitle/jobs/{job_id} - Get subtitle job status
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from .config import get_settings, ensure_subtitle_output_dir
from .errors import SubtitleError
from .models import SubtitleJob, SubtitleJobStatus
from .package_engine import get_package_engine
from .job_store import get_job_store


# Storage paths - match api_server.py configuration
DEFAULT_APP_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.environ.get("CONTENT_SHORT_STORAGE_DIR", DEFAULT_APP_DIR / "storage")).resolve()
OUTPUT_DIR = STORAGE_DIR / "free-viral-shorts"


def _extract_video_id_from_path(video_path: str) -> Optional[str]:
    """
    Extract YouTube video ID from video_path.
    
    Supports:
    - /absolute/path/to/storage/free-viral-shorts/<video_id>/shorts/short_01.mp4
    - storage/free-viral-shorts/<video_id>/shorts/short_01.mp4
    - <video_id>/shorts/short_01.mp4
    
    Returns video_id or None if not found.
    """
    # Pattern for content-short storage: free-viral-shorts/<video_id>/
    pattern = r"(?:free-viral-shorts[/\\]([A-Za-z0-9_-]{11}))"
    match = re.search(pattern, video_path)
    if match:
        return match.group(1)
    
    # Direct video_id if path is just the ID
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_path):
        return video_path
    
    return None


def _infer_opening_duration_from_result(video_path: str) -> float:
    """
    Infer opening_duration from result.json if not provided.
    
    Reads result.json from OUTPUT_DIR / <video_id> / result.json
    and extracts opening_duration from highlights[0] or shorts[0].
    
    Returns 0.0 if not found.
    """
    video_id = _extract_video_id_from_path(video_path)
    if not video_id:
        return 0.0
    
    result_json_path = OUTPUT_DIR / video_id / "result.json"
    if not result_json_path.exists():
        return 0.0
    
    try:
        result_data = json.loads(result_json_path.read_text())
        
        # Try highlights[0].opening_duration first
        highlights = result_data.get("highlights", [])
        if highlights and isinstance(highlights, list):
            first_highlight = highlights[0]
            if isinstance(first_highlight, dict):
                opening_duration = first_highlight.get("opening_duration")
                if opening_duration is not None and isinstance(opening_duration, (int, float)) and opening_duration > 0:
                    return float(opening_duration)
        
        # Try shorts[0].opening_duration
        shorts = result_data.get("shorts", [])
        if shorts and isinstance(shorts, list):
            first_short = shorts[0]
            if isinstance(first_short, dict):
                opening_duration = first_short.get("opening_duration")
                if opening_duration is not None and isinstance(opening_duration, (int, float)) and opening_duration > 0:
                    return float(opening_duration)
        
    except Exception:
        pass
    
    return 0.0


# Security
security = HTTPBearer(auto_error=False)
subtitle_api_token = get_settings().subtitle_api_token


def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """Verify Bearer token."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != subtitle_api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# Request models
class GenerateSubtitleRequest(BaseModel):
    """Request model for subtitle generation."""

    video_path: str = Field(
        ...,
        description="Path to video file (absolute or storage relative)"
    )
    language: str = Field(
        default="id",
        description="Language code (id, en, etc.)"
    )
    output_formats: list[str] = Field(
        default=["ass", "srt"],
        description="Output subtitle formats"
    )
    engine: str = Field(
        default="auto-captions",
        description="Subtitle engine to use"
    )
    style: str = Field(
        default="viral_clip_pro",
        description="Subtitle style"
    )
    burn_subtitle: bool = Field(
        default=False,
        description="Burn subtitle to video"
    )
    transcribe_model: str = Field(
        default="medium",
        description="Whisper model for auto-captions transcription"
    )
    transcribe_preset: str = Field(
        default="accurate",
        description="Transcription quality preset: fast, accurate, or review"
    )
    initial_prompt: str = Field(
        default="",
        description="Optional Whisper initial prompt"
    )
    corrections_file: Optional[str] = Field(
        default=None,
        description="Optional JSON file with transcription corrections"
    )
    audio_preset: Optional[str] = Field(
        default=None,
        description="Optional audio preprocessing preset: plain or speech"
    )


class BurnSubtitleRequest(BaseModel):
    """Request model for subtitle burning."""

    video_path: str = Field(
        ...,
        description="Path to video file"
    )
    language: str = Field(
        default="id",
        description="Language code"
    )
    engine: str = Field(
        default="auto-captions",
        description="Subtitle engine to use"
    )
    style: str = Field(
        default="viral_clip_pro",
        description="Subtitle style"
    )
    replace_original: bool = Field(
        default=False,
        description="Replace original video with burned version"
    )
    transcribe_model: str = Field(
        default="medium",
        description="Whisper model for auto-captions transcription"
    )
    transcribe_preset: str = Field(
        default="accurate",
        description="Transcription quality preset: fast, accurate, or review"
    )
    initial_prompt: str = Field(
        default="",
        description="Optional Whisper initial prompt"
    )
    corrections_file: Optional[str] = Field(
        default=None,
        description="Optional JSON file with transcription corrections"
    )
    audio_preset: Optional[str] = Field(
        default=None,
        description="Optional audio preprocessing preset: plain or speech"
    )


class BurnFromTranscriptRequest(BaseModel):
    """Request model for burning subtitles from known clip transcript."""

    video_path: str = Field(..., description="Path to video file")
    selected_transcript: list[dict[str, Any]] = Field(
        ...,
        description="Clip transcript segments with source-video start/end/text"
    )
    clip_start: float = Field(..., description="Source-video start time of the rendered clip")
    opening_duration: float = Field(
        default=0.0,
        description="Duration of prepended opening narration in seconds"
    )
    language: str = Field(default="id", description="Language code")
    style: str = Field(default="viral_clip_pro", description="Subtitle style")
    replace_original: bool = Field(
        default=False,
        description="Replace original video with burned version"
    )


# Router
router = APIRouter(prefix="/subtitle", tags=["subtitle"])


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    settings = get_settings()
    engine = get_package_engine()
    
    return {
        "ok": True,
        "enable_subtitle_api": settings.enable_subtitle_api,
        "engine": settings.subtitle_engine,
        "fallback_engine": settings.subtitle_fallback_engine,
        "ffmpeg_installed": engine.ffmpeg.check_installed(),
        "auto_captions_installed": engine.auto_captions.check_installed(),
        "whisperx_installed": engine.whisperx.check_installed(),
    }


@router.post("/generate")
async def generate_subtitle(
    request: GenerateSubtitleRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token),
):
    """
    Generate subtitle only.
    
    POST /subtitle/generate
    
    Request:
    {
      "video_path": "/path/to/video.mp4",
      "language": "id",
      "output_formats": ["ass", "srt"],
      "engine": "auto-captions",
      "style": "viral_clip_pro",
      "burn_subtitle": false
    }
    
    Response:
    {
      "job_id": "uuid",
      "status": "completed",
      "video_path": "...",
      "outputs": {
        "ass": ".../subtitle.ass",
        "srt": ".../subtitle.srt",
        "burned_video": null
      },
      "metadata": {
        "language": "id",
        "duration": 52.4,
        "engine": "auto-captions",
        "word_timestamps": true
      }
    }
    """
    settings = get_settings()
    
    if not settings.enable_subtitle_api:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subtitle API is not enabled. Set ENABLE_SUBTITLE_API=true",
        )
    
    # Ensure output directory exists
    ensure_subtitle_output_dir()
    
    # Create job
    job_store = get_job_store()
    job = job_store.create_job(
        video_path=request.video_path,
        language=request.language,
        output_formats=request.output_formats,
        engine=request.engine,
        style=request.style,
        burn_subtitle=request.burn_subtitle,
        transcribe_model=request.transcribe_model,
        transcribe_preset=request.transcribe_preset,
        initial_prompt=request.initial_prompt,
        corrections_file=request.corrections_file,
        audio_preset=request.audio_preset,
    )
    
    # Run generation in background
    background_tasks.add_task(
        _run_subtitle_generation,
        job.job_id,
        request,
    )
    
    return {
        "job_id": job.job_id,
        "status": "pending",
        "status_url": f"/subtitle/jobs/{job.job_id}",
        "result_url": f"/subtitle/jobs/{job.job_id}",
    }


@router.post("/burn")
async def burn_subtitle(
    request: BurnSubtitleRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token),
):
    """
    Generate subtitle and burn to video.
    
    POST /subtitle/burn
    
    Request:
    {
      "video_path": "/path/to/video.mp4",
      "language": "id",
      "engine": "auto-captions",
      "style": "viral_clip_pro",
      "replace_original": false
    }
    
    Response:
    {
      "job_id": "uuid",
      "status": "completed",
      "original_video": ".../video.mp4",
      "burned_video": ".../video_subtitled.mp4",
      "outputs": {
        "ass": ".../subtitle.ass",
        "srt": ".../subtitle.srt"
      }
    }
    """
    settings = get_settings()
    
    if not settings.enable_subtitle_api:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subtitle API is not enabled. Set ENABLE_SUBTITLE_API=true",
        )
    
    # Ensure output directory exists
    ensure_subtitle_output_dir()
    
    # Create job
    job_store = get_job_store()
    job = job_store.create_job(
        video_path=request.video_path,
        language=request.language,
        output_formats=["ass", "srt"],
        engine=request.engine,
        style=request.style,
        burn_subtitle=True,
        transcribe_model=request.transcribe_model,
        transcribe_preset=request.transcribe_preset,
        initial_prompt=request.initial_prompt,
        corrections_file=request.corrections_file,
        audio_preset=request.audio_preset,
    )
    
    # Run generation in background
    background_tasks.add_task(
        _run_subtitle_burn,
        job.job_id,
        request,
    )
    
    return {
        "job_id": job.job_id,
        "status": "pending",
        "status_url": f"/subtitle/jobs/{job.job_id}",
        "result_url": f"/subtitle/jobs/{job.job_id}",
    }


@router.post("/burn-from-transcript")
async def burn_subtitle_from_transcript(
    request: BurnFromTranscriptRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(verify_token),
):
    """Generate subtitles from selected_transcript and burn them without Whisper."""
    settings = get_settings()

    if not settings.enable_subtitle_api:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subtitle API is not enabled. Set ENABLE_SUBTITLE_API=true",
        )

    if not request.selected_transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="selected_transcript is required",
        )

    ensure_subtitle_output_dir()
    job_store = get_job_store()
    job = job_store.create_job(
        video_path=request.video_path,
        language=request.language,
        output_formats=["ass", "srt"],
        engine="selected-transcript",
        style=request.style,
        burn_subtitle=True,
    )

    background_tasks.add_task(
        _run_subtitle_burn_from_transcript,
        job.job_id,
        request,
    )

    return {
        "job_id": job.job_id,
        "status": "pending",
        "status_url": f"/subtitle/jobs/{job.job_id}",
        "result_url": f"/subtitle/jobs/{job.job_id}",
    }


@router.get("/jobs/{job_id}")
async def get_subtitle_job(
    job_id: str,
    token: str = Depends(verify_token),
):
    """
    Get subtitle job status.
    
    GET /subtitle/jobs/{job_id}
    
    Response:
    {
      "job_id": "uuid",
      "status": "pending|processing|completed|failed",
      "error": null,
      "outputs": {}
    }
    """
    job_store = get_job_store()
    
    # Try memory first
    job = job_store.get_job(job_id)
    
    # Try disk
    if job is None:
        job = job_store.get_job_from_disk(job_id)
    
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {job_id}",
        )
    
    # Build response
    response = {
        "job_id": job.job_id,
        "status": job.status,
        "video_path": job.video_path,
    }
    
    if job.outputs:
        response["outputs"] = {
            "ass": job.outputs.ass,
            "srt": job.outputs.srt,
            "vtt": job.outputs.vtt,
            "burned_video": job.outputs.burned_video,
        }
    
    if job.metadata:
        response["metadata"] = {
            "language": job.metadata.language,
            "duration": job.metadata.duration,
            "engine": job.metadata.engine,
            "word_timestamps": job.metadata.word_timestamps,
        }
    
    if job.error:
        response["error"] = job.error
    
    if job.error_code:
        response["error_code"] = job.error_code
    
    if job.created_at:
        response["created_at"] = job.created_at
    
    if job.completed_at:
        response["completed_at"] = job.completed_at
        if job.created_at:
            try:
                created_at = datetime.fromisoformat(str(job.created_at).replace("Z", "+00:00"))
                completed_at = datetime.fromisoformat(str(job.completed_at).replace("Z", "+00:00"))
                response["duration_seconds"] = round((completed_at - created_at).total_seconds(), 3)
            except Exception:
                pass
    
    return response


# Background task functions
def _run_subtitle_generation(job_id: str, request: GenerateSubtitleRequest):
    """Run subtitle generation in background."""
    try:
        engine = get_package_engine()
        engine.generate(
            job_id=job_id,
            video_path=request.video_path,
            language=request.language,
            output_formats=request.output_formats,
            engine=request.engine,
            style=request.style,
            burn_subtitle=request.burn_subtitle,
            transcribe_model=request.transcribe_model,
            transcribe_preset=request.transcribe_preset,
            initial_prompt=request.initial_prompt,
            corrections_file=request.corrections_file,
            audio_preset=request.audio_preset,
        )
    except SubtitleError as e:
        job_store = get_job_store()
        job_store.update_job(
            job_id,
            status="failed",
            error=e.message,
            error_code=e.error_code,
        )
    except Exception as e:
        job_store = get_job_store()
        job_store.update_job(
            job_id,
            status="failed",
            error=str(e)[:500],
            error_code="UNKNOWN_SUBTITLE_ERROR",
        )


def _run_subtitle_burn(job_id: str, request: BurnSubtitleRequest):
    """Run subtitle burn in background."""
    try:
        engine = get_package_engine()
        engine.generate_burn(
            job_id=job_id,
            video_path=request.video_path,
            language=request.language,
            engine=request.engine,
            style=request.style,
            replace_original=request.replace_original,
            transcribe_model=request.transcribe_model,
            transcribe_preset=request.transcribe_preset,
            initial_prompt=request.initial_prompt,
            corrections_file=request.corrections_file,
            audio_preset=request.audio_preset,
        )
    except SubtitleError as e:
        job_store = get_job_store()
        job_store.update_job(
            job_id,
            status="failed",
            error=e.message,
            error_code=e.error_code,
        )
    except Exception as e:
        job_store = get_job_store()
        job_store.update_job(
            job_id,
            status="failed",
            error=str(e)[:500],
            error_code="UNKNOWN_SUBTITLE_ERROR",
        )


def _run_subtitle_burn_from_transcript(job_id: str, request: BurnFromTranscriptRequest):
    """Run transcript-based subtitle burn in background."""
    try:
        # Infer opening_duration from result.json if not provided (equals 0)
        # This makes the backend robust even when n8n doesn't send opening_duration
        opening_duration = request.opening_duration
        if opening_duration == 0.0:
            inferred = _infer_opening_duration_from_result(request.video_path)
            if inferred > 0:
                opening_duration = inferred
        
        engine = get_package_engine()
        engine.generate_from_transcript_burn(
            job_id=job_id,
            video_path=request.video_path,
            selected_transcript=request.selected_transcript,
            clip_start=request.clip_start,
            opening_duration=opening_duration,
            language=request.language,
            style=request.style,
            replace_original=request.replace_original,
        )
    except SubtitleError as e:
        job_store = get_job_store()
        job_store.update_job(
            job_id,
            status="failed",
            error=e.message,
            error_code=e.error_code,
        )
    except Exception as e:
        job_store = get_job_store()
        job_store.update_job(
            job_id,
            status="failed",
            error=str(e)[:500],
            error_code="UNKNOWN_SUBTITLE_ERROR",
        )


# Create router
def create_subtitle_router() -> APIRouter:
    """Create and return subtitle router."""
    return router
