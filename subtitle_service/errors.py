"""
Subtitle Service Error Definitions.

Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.
Error codes:
- VIDEO_NOT_FOUND
- INVALID_VIDEO_FORMAT
- PACKAGE_NOT_INSTALLED
- FFMPEG_NOT_FOUND
- NO_AUDIO_STREAM
- PACKAGE_EXECUTION_FAILED
- SUBTITLE_OUTPUT_NOT_FOUND
- BURN_FAILED
- BURN_FAILED_LIBASS_NOT_AVAILABLE
- NO_VISIBLE_SUBTITLE_EVENTS
- UNKNOWN_SUBTITLE_ERROR
"""


class SubtitleError(Exception):
    """Base exception for subtitle service."""

    def __init__(self, message: str, error_code: str = "UNKNOWN_SUBTITLE_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error": self.message,
            "error_code": self.error_code,
        }


class VideoNotFoundError(SubtitleError):
    """Video file not found."""

    def __init__(self, video_path: str, detail: str = None):
        message = f"Video file not found: {video_path}"
        if detail:
            message += f" - {detail}"
        super().__init__(
            message=message,
            error_code="VIDEO_NOT_FOUND"
        )
        self.video_path = video_path
        self.detail = detail


class InvalidVideoFormatError(SubtitleError):
    """Invalid video format."""

    def __init__(self, video_path: str, reason: str = ""):
        message = f"Invalid video format: {video_path}"
        if reason:
            message += f" - {reason}"
        super().__init__(
            message=message,
            error_code="INVALID_VIDEO_FORMAT"
        )
        self.video_path = video_path


class PackageNotInstalledError(SubtitleError):
    """Required package not installed."""

    def __init__(self, package_name: str):
        super().__init__(
            message=f"Package not installed: {package_name}",
            error_code="PACKAGE_NOT_INSTALLED"
        )
        self.package_name = package_name


class FFmpegNotFoundError(SubtitleError):
    """FFmpeg binary not found."""

    def __init__(self, ffmpeg_path: str = "/usr/bin/ffmpeg"):
        super().__init__(
            message=f"FFmpeg not found at: {ffmpeg_path}",
            error_code="FFMPEG_NOT_FOUND"
        )
        self.ffmpeg_path = ffmpeg_path


class NoAudioStreamError(SubtitleError):
    """Video has no audio stream."""

    def __init__(self, video_path: str):
        super().__init__(
            message=f"Input video has no audio stream; auto-captions requires audio: {video_path}",
            error_code="NO_AUDIO_STREAM"
        )
        self.video_path = video_path


class PackageExecutionError(SubtitleError):
    """Package execution failed."""

    def __init__(
        self,
        package_name: str,
        command: str,
        returncode: int,
        stdout: str = "",
        stderr: str = ""
    ):
        message = f"Package execution failed: {package_name}"
        message += f"\nCommand: {command}"
        message += f"\nReturn code: {returncode}"
        if stderr:
            message += f"\nStderr: {stderr[:500]}"
        super().__init__(
            message=message,
            error_code="PACKAGE_EXECUTION_FAILED"
        )
        self.package_name = package_name
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class SubtitleOutputNotFoundError(SubtitleError):
    """Subtitle output file not found."""

    def __init__(self, output_path: str, job_id: str = ""):
        message = f"Subtitle output not found: {output_path}"
        if job_id:
            message += f" (job: {job_id})"
        super().__init__(
            message=message,
            error_code="SUBTITLE_OUTPUT_NOT_FOUND"
        )
        self.output_path = output_path
        self.job_id = job_id


class BurnError(SubtitleError):
    """Failed to burn subtitle to video."""

    def __init__(self, video_path: str, subtitle_path: str, reason: str = ""):
        message = f"Failed to burn subtitle to video: {video_path}"
        message += f"\nSubtitle: {subtitle_path}"
        if reason:
            message += f"\nReason: {reason}"
        super().__init__(
            message=message,
            error_code="BURN_FAILED"
        )
        self.video_path = video_path
        self.subtitle_path = subtitle_path


class UnknownSubtitleError(SubtitleError):
    """Unknown subtitle error."""

    def __init__(self, reason: str):
        super().__init__(
            message=f"Unknown subtitle error: {reason}",
            error_code="UNKNOWN_SUBTITLE_ERROR"
        )
        self.reason = reason


class BurnLibassNotAvailableError(SubtitleError):
    """Burn subtitle failed due to FFmpeg not having libass support."""

    def __init__(self, ffmpeg_version: str = "", ffmpeg_filters: str = ""):
        message = (
            "Subtitle files were generated, but FFmpeg cannot burn ASS subtitles "
            "because this FFmpeg build has no libass support. "
            "Install/reinstall FFmpeg with libass support.\n"
            "Solution:\n"
            "  brew update\n"
            "  brew install libass\n"
            "  brew reinstall ffmpeg\n"
            "  ffmpeg -version | grep enable-libass\n"
            "  ffmpeg -filters | grep -E 'ass|subtitles'"
        )
        super().__init__(
            message=message,
            error_code="BURN_FAILED_LIBASS_NOT_AVAILABLE"
        )
        self.ffmpeg_version = ffmpeg_version
        self.ffmpeg_filters = ffmpeg_filters


class NoVisibleSubtitleEventsError(SubtitleError):
    """Selected transcript did not produce visible subtitle events."""

    def __init__(self):
        super().__init__(
            message="selected_transcript did not produce any visible subtitle events",
            error_code="NO_VISIBLE_SUBTITLE_EVENTS",
        )
