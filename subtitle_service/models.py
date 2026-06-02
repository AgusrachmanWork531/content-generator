"""
Subtitle Service Data Models.

Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SubtitleEngine(str, Enum):
    """Available subtitle engines."""

    AUTO_CAPTIONS = "auto-captions"
    WHISPERX = "whisperx"
    CAPTIONS = "captions"


class SubtitleStyle(str, Enum):
    """Subtitle styles for short videos."""

    SHORTS_PRO = "shorts_pro"
    VIRAL_CLIP_PRO = "viral_clip_pro"
    SHORTS_PRO_POP = "shorts_pro_pop"
    DEFAULT = "default"


class SubtitleFormat(str, Enum):
    """Subtitle output formats."""

    ASS = "ass"
    SRT = "srt"
    VTT = "vtt"


class SubtitleJobStatus(str, Enum):
    """Subtitle job status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNING = "completed_with_warning"
    FAILED = "failed"


# Request models
class SubtitleRequest(BaseModel):
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


class SubtitleBurnRequest(BaseModel):
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


# Output models
class SubtitleOutput(BaseModel):
    """Subtitle output file paths."""

    ass: Optional[str] = Field(
        default=None,
        description="Path to ASS subtitle file"
    )
    srt: Optional[str] = Field(
        default=None,
        description="Path to SRT subtitle file"
    )
    vtt: Optional[str] = Field(
        default=None,
        description="Path to VTT subtitle file"
    )
    burned_video: Optional[str] = Field(
        default=None,
        description="Path to burned video file"
    )


class SubtitleMetadata(BaseModel):
    """Subtitle generation metadata."""

    language: str = Field(..., description="Detected/used language")
    duration: float = Field(..., description="Video duration in seconds")
    engine: str = Field(..., description="Engine used")
    word_timestamps: bool = Field(
        default=False,
        description="Whether word-level timestamps are available"
    )


# Job models
class SubtitleJob(BaseModel):
    """Subtitle job model."""

    job_id: str = Field(..., description="Unique job ID")
    status: str = Field(..., description="Job status")
    video_path: str = Field(..., description="Input video path")
    outputs: Optional[SubtitleOutput] = Field(
        default=None,
        description="Output files"
    )
    metadata: Optional[SubtitleMetadata] = Field(
        default=None,
        description="Generation metadata"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if failed"
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Error code"
    )
    created_at: Optional[str] = Field(
        default=None,
        description="Job creation timestamp"
    )
    completed_at: Optional[str] = Field(
        default=None,
        description="Job completion timestamp"
    )


class SubtitleJobResponse(BaseModel):
    """Response model for subtitle job status."""

    job_id: str = Field(..., description="Unique job ID")
    status: str = Field(..., description="Job status")
    video_path: Optional[str] = Field(
        default=None,
        description="Input video path"
    )
    outputs: Optional[dict] = Field(
        default=None,
        description="Output files"
    )
    metadata: Optional[dict] = Field(
        default=None,
        description="Generation metadata"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message"
    )
