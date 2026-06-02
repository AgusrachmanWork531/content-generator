"""
Subtitle Service API Routes.

FastAPI routes for subtitle generation.
Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.

API Endpoints:
1. POST /subtitle/generate - Generate subtitle only
2. POST /subtitle/burn - Generate subtitle + burn video
3. GET /subtitle/jobs/{job_id} - Get subtitle job status
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from .config import get_settings, ensure_subtitle_output_dir
from .errors import SubtitleError
from .models import SubtitleJob, SubtitleJobStatus
from .package_engine import get_package_engine
from .job_store import get_job_store


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


# Create router
def create_subtitle_router() -> APIRouter:
    """Create and return subtitle router."""
    return router
