"""
FFmpeg Adapter for subtitle service.

Wrapper for FFmpeg binary operations.
Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.

FFmpeg is used for:
- extract audio
- burn ASS/subtitle to video
- probing video metadata
"""

import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .config import get_settings
from .errors import FFmpegNotFoundError


class FFmpegAdapter:
    """FFmpeg wrapper for subtitle operations."""

    def __init__(self):
        self.settings = get_settings()
        self._ffmpeg_path: Optional[str] = None
        self._libass_available: Optional[bool] = None
        self._ass_filter_available: Optional[bool] = None

    @property
    def ffmpeg_path(self) -> str:
        """Get FFmpeg path."""
        if self._ffmpeg_path is None:
            # Try to find ffmpeg
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                self._ffmpeg_path = ffmpeg
            else:
                self._ffmpeg_path = self.settings.ffmpeg_bin
        return self._ffmpeg_path

    def check_installed(self) -> bool:
        """Check if FFmpeg is installed."""
        return shutil.which("ffmpeg") is not None

    def ensure_installed(self):
        """Ensure FFmpeg is installed."""
        if not self.check_installed():
            raise FFmpegNotFoundError(self.ffmpeg_path)

    def get_version(self) -> str:
        """Get FFmpeg version string."""
        self.ensure_installed()
        result = subprocess.run(
            [self.ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout if result.returncode == 0 else ""

    def get_filters(self) -> str:
        """Get FFmpeg filters list."""
        self.ensure_installed()
        result = subprocess.run(
            [self.ffmpeg_path, "-filters"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout if result.returncode == 0 else ""

    def check_libass_support(self) -> bool:
        """
        Check if FFmpeg has libass support compiled in.
        
        Returns True if --enable-libass is present in version output.
        """
        if self._libass_available is None:
            version_output = self.get_version()
            self._libass_available = "--enable-libass" in version_output
        return self._libass_available

    def check_ass_filter_available(self) -> bool:
        """
        Check if ass/subtitles filter is available.
        
        Returns True if ass filter exists in -filters output.
        """
        if self._ass_filter_available is None:
            filters_output = self.get_filters()
            # Check for ass or subtitles filter
            self._ass_filter_available = (
                "ass " in filters_output or 
                "  ass " in filters_output or
                "subtitles " in filters_output or
                "  subtitles " in filters_output
            )
        return self._ass_filter_available

    def can_burn_subtitles(self) -> Tuple[bool, str]:
        """
        Check if FFmpeg can burn subtitles.
        
        Returns tuple of (can_burn, reason).
        If can_burn is False, reason explains what's missing.
        """
        if not self.check_installed():
            return (False, "FFmpeg is not installed")
        
        has_libass = self.check_libass_support()
        has_filter = self.check_ass_filter_available()
        
        if has_libass and has_filter:
            return (True, "libass and ass filter available")
        
        reasons = []
        if not has_libass:
            reasons.append("FFmpeg has no libass support (--enable-libass)")
        if not has_filter:
            reasons.append("FFmpeg has no ass/subtitles filter")
        
        return (False, "; ".join(reasons))

    def get_video_info(self, video_path: Path) -> dict:
        """
        Get video metadata using ffprobe.
        
        Returns dict with:
        - duration: float (seconds)
        - width: int
        - height: int
        - fps: float
        - codec: str
        """
        self.ensure_installed()
        
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise FFmpegNotFoundError("ffprobe not found")

        cmd = [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,codec_name,duration",
            "-of", "json",
            str(video_path),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")

        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0] if data.get("streams") else {}

        # Parse frame rate
        fps = 0.0
        fps_str = stream.get("r_frame_rate", "0/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            if int(den) > 0:
                fps = int(num) / int(den)
        elif fps_str:
            fps = float(fps_str)

        return {
            "duration": float(stream.get("duration", 0.0)),
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "fps": fps,
            "codec": stream.get("codec_name", ""),
        }

    def has_audio_stream(self, video_path: Path) -> bool:
        """
        Return True when the video has at least one audio stream.
        """
        self.ensure_installed()

        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise FFmpegNotFoundError("ffprobe not found")

        cmd = [
            ffprobe,
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "json",
            str(video_path),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe audio check failed: {result.stderr}")

        data = json.loads(result.stdout)
        return bool(data.get("streams"))

    def extract_audio(
        self,
        video_path: Path,
        audio_path: Path,
        format: str = "wav",
    ) -> Path:
        """
        Extract audio from video.
        
        Returns path to extracted audio file.
        """
        self.ensure_installed()

        cmd = [
            self.ffmpeg_path,
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le" if format == "wav" else format,
            "-ar", "16000",
            "-ac", "1",
            "-y",
            str(audio_path),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Audio extraction failed: {result.stderr}")

        return audio_path

    def burn_subtitle(
        self,
        video_path: Path,
        subtitle_path: Path,
        output_path: Path,
        subtitle_style: str = "viral_clip_pro",
    ) -> Path:
        """
        Burn subtitle to video using ASS/SSA format.
        
        Returns path to burned video.
        """
        self.ensure_installed()

        # Use absolute paths and escape properly
        video_abs = str(video_path.resolve())
        subtitle_abs = str(subtitle_path.resolve())
        output_abs = str(output_path.resolve())

        # Determine subtitle codec based on format
        # For ASS files, use ass= filter
        # For SRT files, use subtitles= filter
        if subtitle_path.suffix.lower() in (".ass", ".ssa"):
            # Use ass filter with escaped path
            filter_expr = f"ass={shlex.quote(subtitle_abs)}"
        else:
            # Use subtitles filter
            filter_expr = f"subtitles={shlex.quote(subtitle_abs)}"

        # Build FFmpeg command
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", video_abs,
            "-vf", filter_expr,
            "-c:a", "copy",
            output_abs,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Subtitle burn failed: {result.stderr}")

        return output_path

    def probe_duration(self, video_path: Path) -> float:
        """Get video duration in seconds."""
        info = self.get_video_info(video_path)
        return info.get("duration", 0.0)


# Global instance
_ffmpeg_adapter: Optional[FFmpegAdapter] = None


def get_ffmpeg_adapter() -> FFmpegAdapter:
    """Get global FFmpeg adapter instance."""
    global _ffmpeg_adapter
    if _ffmpeg_adapter is None:
        _ffmpeg_adapter = FFmpegAdapter()
    return _ffmpeg_adapter
