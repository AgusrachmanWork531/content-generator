"""
Subtitle Service - Independent subtitle generation API.

This service generates subtitles from existing video shorts using external package engines:
- auto-captions (primary)
- WhisperX (fallback)
- captions (format converter)

Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements:
- Independent and isolated from main pipeline
- Uses full package features, not local reimplementation
- Provides API and CLI interfaces
"""

__version__ = "1.0.0"

from .config import Settings, get_settings
from .models import (
    SubtitleRequest,
    SubtitleBurnRequest,
    SubtitleJob,
    SubtitleOutput,
    SubtitleJobStatus,
)
from .errors import (
    SubtitleError,
    VideoNotFoundError,
    InvalidVideoFormatError,
    PackageNotInstalledError,
    FFmpegNotFoundError,
    PackageExecutionError,
    SubtitleOutputNotFoundError,
    BurnError,
    UnknownSubtitleError,
    BurnLibassNotAvailableError,
)
from .package_engine import PackageEngine, get_package_engine
from .job_store import JobStore, get_job_store
from .ffmpeg_adapter import FFmpegAdapter, get_ffmpeg_adapter

__all__ = [
    "__version__",
    "Settings",
    "get_settings",
    "SubtitleRequest",
    "SubtitleBurnRequest",
    "SubtitleJob",
    "SubtitleOutput",
    "SubtitleJobStatus",
    "SubtitleError",
    "VideoNotFoundError",
    "InvalidVideoFormatError",
    "PackageNotInstalledError",
    "FFmpegNotFoundError",
    "PackageExecutionError",
    "SubtitleOutputNotFoundError",
    "BurnError",
    "UnknownSubtitleError",
    "BurnLibassNotAvailableError",
    # Package engine functions
    "get_package_engine",
    "PackageEngine",
    # Job store functions
    "get_job_store",
    "JobStore",
    # FFmpeg adapter functions
    "get_ffmpeg_adapter",
    "FFmpegAdapter",
]
