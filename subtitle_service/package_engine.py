"""
Package Engine Orchestrator for subtitle service.

Coordinates between different subtitle engines.
Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.

Engine priority:
1. auto-captions (primary)
2. whisperx (fallback)
3. captions (format converter only)
"""

import json
import shutil
from pathlib import Path
from typing import Optional

from .config import get_settings
from .errors import (
    VideoNotFoundError,
    InvalidVideoFormatError,
    PackageExecutionError,
    SubtitleOutputNotFoundError,
    BurnError,
    BurnLibassNotAvailableError,
    NoAudioStreamError,
    UnknownSubtitleError,
    NoVisibleSubtitleEventsError,
)
from .models import SubtitleOutput, SubtitleMetadata, SubtitleJobStatus
from .autocaptions_adapter import get_auto_captions_adapter, AutoCaptionsAdapter
from .whisperx_adapter import get_whisperx_adapter, WhisperXAdapter
from .captions_adapter import get_captions_adapter, CaptionsAdapter
from .ffmpeg_adapter import get_ffmpeg_adapter, FFmpegAdapter
from .job_store import get_job_store, JobStore


class PackageEngine:
    """Orchestrates subtitle generation using external packages."""

    def __init__(self):
        self.settings = get_settings()
        self.auto_captions = get_auto_captions_adapter()
        self.whisperx = get_whisperx_adapter()
        self.captions = get_captions_adapter()
        self.ffmpeg = get_ffmpeg_adapter()
        self.job_store = get_job_store()

    def validate_video(self, video_path: Path) -> tuple[bool, Optional[str]]:
        """Validate video file."""
        if not video_path.exists():
            return (False, f"Video not found: {video_path}")

        valid_formats = (".mp4", ".mov", ".mkv", ".webm", ".avi")
        if video_path.suffix.lower() not in valid_formats:
            return (False, f"Invalid format: {video_path.suffix}")

        try:
            info = self.ffmpeg.get_video_info(video_path)
            if info.get("duration", 0) <= 0:
                return (False, f"Invalid video duration")
        except Exception as e:
            return (False, f"Video read error: {e}")

        return (True, None)

    def generate(
        self,
        job_id: str,
        video_path: str,
        language: str = "id",
        output_formats: list[str] = None,
        engine: str = "auto-captions",
        style: str = "viral_clip_pro",
        burn_subtitle: bool = False,
        transcribe_model: str = "medium",
        transcribe_preset: str = "accurate",
        initial_prompt: str = "",
        corrections_file: Optional[str] = None,
        audio_preset: Optional[str] = None,
    ) -> dict:
        """Generate subtitles using package engine."""
        if output_formats is None:
            output_formats = ["ass", "srt"]

        resolved_path = self.job_store.resolve_video_path(video_path)

        is_valid, error = self.validate_video(resolved_path)
        if not is_valid:
            raise VideoNotFoundError(video_path, error)

        job_dir = self.job_store.get_job_dir(job_id)

        video_info = self.ffmpeg.get_video_info(resolved_path)
        duration = video_info.get("duration", 0.0)

        if engine == "auto-captions" and not self.ffmpeg.has_audio_stream(resolved_path):
            raise NoAudioStreamError(str(resolved_path))

        self.job_store.update_job(job_id, status="processing")

        outputs = None
        used_engine = engine
        error_message = ""

        # Try primary engine
        if engine == "auto-captions":
            # Explicit auto-captions - fail fast, no fallback to WhisperX
            print(f"[PackageEngine] Starting auto-captions generation at {job_dir.name}")

            if not self.auto_captions.check_installed():
                error_msg = "Package auto-captions not installed"
                self.job_store.update_job(job_id, status="failed", error=error_msg)
                raise PackageExecutionError(
                    package_name="auto-captions",
                    command="auto-captions",
                    returncode=-1,
                    stderr=error_msg,
                )

            try:
                outputs = self.auto_captions.generate(
                    input_video=resolved_path,
                    output_dir=job_dir,
                    language=language,
                    style=style,
                    output_formats=output_formats,
                    burn=burn_subtitle,
                    transcribe_model=transcribe_model,
                    transcribe_preset=transcribe_preset,
                    initial_prompt=initial_prompt,
                    corrections_file=corrections_file,
                    audio_preset=audio_preset,
                )
                used_engine = "auto-captions"
                print(f"[PackageEngine] Auto-captions generation completed successfully")
            except Exception as e:
                error_message = str(e)
                print(f"[PackageEngine] Auto-captions FAILED: {error_message}")
                # Fail fast - do NOT fall back to WhisperX for explicit auto-captions
                self.job_store.update_job(
                    job_id,
                    status="failed",
                    error=error_message,
                )
                raise UnknownSubtitleError(
                    f"Auto-captions failed (engine=auto-captions): {error_message}"
                )

        elif engine == "whisperx":
            outputs = self._try_whisperx(resolved_path, job_dir, language, output_formats)
            used_engine = "whisperx"
        else:
            # Unknown engine, try auto-captions as default
            try:
                outputs = self.auto_captions.generate(
                    input_video=resolved_path,
                    output_dir=job_dir,
                    language=language,
                    style=style,
                    output_formats=output_formats,
                    burn=burn_subtitle,
                    transcribe_model=transcribe_model,
                    transcribe_preset=transcribe_preset,
                    initial_prompt=initial_prompt,
                    corrections_file=corrections_file,
                    audio_preset=audio_preset,
                )
                used_engine = "auto-captions"
            except Exception as e:
                error_message = str(e)

        # If outputs still empty, try emergency fallback
        if outputs is None or not outputs:
            if self.settings.subtitle_allow_emergency_approx_timing:
                try:
                    outputs = self._emergency_fallback(resolved_path, job_dir, language, output_formats)
                    used_engine = "emergency_fallback"
                except Exception as e:
                    raise UnknownSubtitleError(str(e))
            else:
                raise UnknownSubtitleError(f"No outputs generated, engine={engine}, error={error_message}")

        # Handle subtitle burning if requested
        # Note: The burn is now handled in auto_captions_adapter.generate() when burn=True
        # but we also need to check if it wasn't called there and handle the case manually
        burn_error_message = ""
        burn_error_code = None
        burn_status = "completed"

        if burn_subtitle and not outputs.get("burned_video"):
            # First check if FFmpeg can burn subtitles
            can_burn, burn_reason = self.ffmpeg.can_burn_subtitles()
            
            if not can_burn:
                # FFmpeg cannot burn - mark as completed_with_warning
                burn_error_message = burn_reason
                burn_error_code = "BURN_FAILED_LIBASS_NOT_AVAILABLE"
                burn_status = "completed_with_warning"
                
                # Get version and filters for logging
                ffmpeg_version = self.ffmpeg.get_version()
                ffmpeg_filters = self.ffmpeg.get_filters()
                self.job_store.save_ffmpeg_log(
                    job_id,
                    version=ffmpeg_version,
                    filters=ffmpeg_filters,
                    command="",
                    stderr=burn_reason,
                )
            else:
                # FFmpeg can burn but burn wasn't done - try to burn now
                try:
                    subtitle_path = None
                    if outputs.get("ass"):
                        subtitle_path = Path(outputs["ass"])
                    elif outputs.get("srt"):
                        subtitle_path = Path(outputs["srt"])
                    
                    if subtitle_path and subtitle_path.exists():
                        output_video = job_dir / "video_subtitled.mp4"
                        burned_video = self.ffmpeg.burn_subtitle(
                            video_path=resolved_path,
                            subtitle_path=subtitle_path,
                            output_path=output_video,
                        )
                        outputs["burned_video"] = str(burned_video)
                        
                        # Log success (command logged internally by ffmpeg adapter)
                except Exception as e:
                    # Burn attempted but failed
                    burn_error_message = str(e)
                    burn_error_code = "BURN_FAILED"
                    burn_status = "completed_with_warning"

        # Build output object
        subtitle_output = SubtitleOutput(
            ass=outputs.get("ass"),
            srt=outputs.get("srt"),
            vtt=outputs.get("vtt"),
            burned_video=outputs.get("burned_video"),
        )

        metadata = SubtitleMetadata(
            language=language,
            duration=duration,
            engine=used_engine,
            word_timestamps=(used_engine in ("whisperx", "auto-captions")),
        )

        # Set error if burn failed
        final_error = error_message
        final_error_code = None
        if burn_error_message:
            final_error = burn_error_message
            final_error_code = burn_error_code

        # Use appropriate status
        final_status = burn_status if burn_subtitle else "completed"

        self.job_store.update_job(
            job_id,
            status=final_status,
            outputs=subtitle_output,
            metadata=metadata,
            error=final_error,
            error_code=final_error_code,
        )

        return {
            "outputs": outputs,
            "metadata": metadata,
        }

    def _try_whisperx(self, video_path: Path, output_dir: Path, language: str, output_formats: list[str]) -> dict:
        """Try WhisperX engine."""
        if not self.whisperx.check_installed():
            raise PackageExecutionError(
                package_name="whisperx",
                command="whisperx",
                returncode=-1,
                stderr="Package not installed",
            )

        return self.whisperx.generate(
            input_video=video_path,
            output_dir=output_dir,
            language=language,
            output_formats=output_formats,
        )

    def _emergency_fallback(self, video_path: Path, output_dir: Path, language: str, output_formats: list[str]) -> dict:
        """Emergency approximate timing fallback."""
        raise UnknownSubtitleError(
            f"Emergency fallback not implemented - both primary and fallback engines failed. Video: {video_path}"
        )

    def generate_burn(
        self,
        job_id: str,
        video_path: str,
        language: str = "id",
        engine: str = "auto-captions",
        style: str = "viral_clip_pro",
        replace_original: bool = False,
        transcribe_model: str = "medium",
        transcribe_preset: str = "accurate",
        initial_prompt: str = "",
        corrections_file: Optional[str] = None,
        audio_preset: Optional[str] = None,
    ) -> dict:
        """Generate and burn subtitles to video."""
        result = self.generate(
            job_id=job_id,
            video_path=video_path,
            language=language,
            output_formats=["ass", "srt"],
            engine=engine,
            style=style,
            burn_subtitle=True,
            transcribe_model=transcribe_model,
            transcribe_preset=transcribe_preset,
            initial_prompt=initial_prompt,
            corrections_file=corrections_file,
            audio_preset=audio_preset,
        )

        outputs = result.get("outputs") or {}
        burned_video_value = outputs.get("burned_video")
        subtitle_path = outputs.get("ass") or outputs.get("srt") or ""

        if not burned_video_value:
            raise BurnError(
                video_path=video_path,
                subtitle_path=subtitle_path,
                reason="Burned video output was not generated",
            )

        burned_video = Path(burned_video_value)
        if not burned_video.exists() or burned_video.stat().st_size <= 0:
            raise BurnError(
                video_path=video_path,
                subtitle_path=subtitle_path,
                reason=f"Burned video is missing or empty: {burned_video}",
            )

        if replace_original:
            original_video = self.job_store.resolve_video_path(video_path)
            backup_video = original_video.with_name(
                f"{original_video.name}.pre_subtitle.bak"
            )
            replace_tmp = original_video.with_name(
                f"{original_video.name}.subtitle.tmp"
            )

            if not backup_video.exists():
                shutil.copy2(original_video, backup_video)

            shutil.copy2(burned_video, replace_tmp)
            if not replace_tmp.exists() or replace_tmp.stat().st_size <= 0:
                raise BurnError(
                    video_path=str(original_video),
                    subtitle_path=subtitle_path,
                    reason=f"Replacement temp video is missing or empty: {replace_tmp}",
                )

            replace_tmp.replace(original_video)
            if not original_video.exists() or original_video.stat().st_size <= 0:
                raise BurnError(
                    video_path=str(original_video),
                    subtitle_path=subtitle_path,
                    reason="Original video replacement failed",
                )

            outputs["burned_video"] = str(original_video)
            self.job_store.update_job(
                job_id,
                status=SubtitleJobStatus.COMPLETED.value,
                outputs=SubtitleOutput(
                    ass=outputs.get("ass"),
                    srt=outputs.get("srt"),
                    vtt=outputs.get("vtt"),
                    burned_video=outputs.get("burned_video"),
                ),
                metadata=result.get("metadata"),
            )

        return result

    @staticmethod
    def _calculate_visible_transcript_interval(
        start: float,
        end: float,
        clip_start: float,
        opening_duration: float,
        max_duration: float,
    ) -> Optional[tuple[float, float]]:
        """Map a source transcript interval into the final video timeline."""
        if end <= start:
            return None

        content_duration = max_duration - opening_duration
        if content_duration <= 0:
            return None

        source_relative_start = start - clip_start
        source_relative_end = end - clip_start

        if source_relative_end <= 0:
            return None

        if source_relative_start >= content_duration:
            return None

        content_start = max(0.0, source_relative_start)
        content_end = min(source_relative_end, content_duration)
        if content_end <= content_start:
            return None

        return (
            content_start + opening_duration,
            content_end + opening_duration,
        )

    def _generate_ass_from_transcript(
        self,
        transcript: list,
        output_path,
        clip_start: float,
        opening_duration: float,
        style: str,
        max_duration: float,
    ) -> int:
        """Generate ASS subtitle file from transcript segments.

        Returns:
            int: Number of visible subtitle events in the generated ASS file.
        """
        style_config = self._get_ass_style(style)
        lines = [
            "[Script Info]",
            f"Title: {style}",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: {style}, {style_config}",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        event_count = 0

        for segment in transcript:
            if not isinstance(segment, dict):
                continue
            text = segment.get("text", "")
            if not text or not isinstance(text, str) or not text.strip():
                continue
            start_val = segment.get("start")
            end_val = segment.get("end")
            if start_val is None or end_val is None:
                continue
            try:
                start = float(start_val)
                end = float(end_val)
            except (ValueError, TypeError):
                continue

            interval = self._calculate_visible_transcript_interval(
                start=start,
                end=end,
                clip_start=clip_start,
                opening_duration=opening_duration,
                max_duration=max_duration,
            )
            if interval is None:
                continue
            adjusted_start, adjusted_end = interval

            start_str = self._format_ass_timestamp(adjusted_start)
            end_str = self._format_ass_timestamp(adjusted_end)
            # Escape backslashes and newlines for ASS format
            text_escaped = text.replace(chr(92), chr(92)+chr(92)).replace(chr(10), chr(92)+"N")

            lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{text_escaped}")
            event_count += 1

        output_path.write_text(chr(10).join(lines), encoding="utf-8")
        return event_count

    def generate_from_transcript_burn(
        self,
        job_id: str,
        video_path: str,
        selected_transcript: list,
        clip_start: float = 0.0,
        opening_duration: float = 0.0,
        language: str = "id",
        style: str = "viral_clip_pro",
        replace_original: bool = False,
    ) -> dict:
        """Generate subtitles from known transcript and burn to video."""
        resolved_path = self.job_store.resolve_video_path(video_path)

        is_valid, error = self.validate_video(resolved_path)
        if not is_valid:
            raise VideoNotFoundError(video_path, error)

        job_dir = self.job_store.get_job_dir(job_id)
        video_info = self.ffmpeg.get_video_info(resolved_path)
        duration = video_info.get("duration", 0.0)

        self.job_store.update_job(job_id, status="processing")

        # Generate ASS subtitle from transcript
        ass_path = job_dir / "subtitle.ass"
        ass_event_count = self._generate_ass_from_transcript(
            transcript=selected_transcript,
            output_path=ass_path,
            clip_start=clip_start,
            opening_duration=opening_duration,
            style=style,
            max_duration=float(duration),
        )

        if not ass_path.exists():
            self.job_store.update_job(
                job_id,
                status=SubtitleJobStatus.FAILED.value,
                error="ASS file not generated",
                error_code="ASS_FILE_NOT_GENERATED",
            )
            raise UnknownSubtitleError("ASS file was not generated")

        # Validate that ASS file has visible subtitle events
        if ass_event_count <= 0:
            self.job_store.update_job(
                job_id,
                status=SubtitleJobStatus.FAILED.value,
                error="selected_transcript did not produce any visible subtitle events",
                error_code="NO_VISIBLE_SUBTITLE_EVENTS",
            )
            raise NoVisibleSubtitleEventsError()

        # Also generate SRT
        srt_path = job_dir / "subtitle.srt"
        try:
            self._generate_srt_from_transcript(
                transcript=selected_transcript,
                output_path=srt_path,
                clip_start=clip_start,
                opening_duration=opening_duration,
                max_duration=float(duration),
            )
        except Exception:
            pass

        # Burn subtitle - with proper validation and error handling
        burned_video = None
        can_burn, burn_reason = self.ffmpeg.can_burn_subtitles()

        # Fail if cannot burn subtitles
        if not can_burn:
            self.job_store.update_job(job_id, status="failed", error=burn_reason)
            raise BurnError(
                video_path=str(resolved_path),
                subtitle_path=str(ass_path),
                reason=burn_reason,
            )

        # Attempt to burn subtitle
        try:
            output_video = job_dir / "video_subtitled.mp4"
            burned_video = self.ffmpeg.burn_subtitle(
                video_path=resolved_path,
                subtitle_path=ass_path,
                output_path=output_video,
            )
        except Exception as e:
            self.job_store.update_job(job_id, status="failed", error=str(e))
            raise BurnError(
                video_path=str(resolved_path),
                subtitle_path=str(ass_path),
                reason=str(e),
            )

        # Validate burned video exists and not empty
        if not burned_video or not Path(burned_video).exists():
            self.job_store.update_job(job_id, status="failed", error="Burned video not generated")
            raise BurnError(
                video_path=str(resolved_path),
                subtitle_path=str(ass_path),
                reason="Burned video was not generated",
            )

        burned_video_path = Path(burned_video)
        if not burned_video_path.exists() or burned_video_path.stat().st_size <= 0:
            self.job_store.update_job(job_id, status="failed", error="Burned video is missing or empty")
            raise BurnError(
                video_path=str(resolved_path),
                subtitle_path=str(ass_path),
                reason=f"Burned video is missing or empty: {burned_video}",
            )

        outputs = {
            "ass": str(ass_path) if ass_path.exists() else None,
            "srt": str(srt_path) if srt_path.exists() else None,
            "burned_video": str(burned_video) if burned_video else None,
        }

        # Handle replace_original flag
        if replace_original:
            # Original video path
            original_video = self.job_store.resolve_video_path(video_path)

            # Backup path
            backup_video = original_video.with_name(
                f"{original_video.name}.pre_subtitle.bak"
            )

            # Temporary replacement path
            replace_tmp = original_video.with_name(
                f"{original_video.name}.subtitle.tmp"
            )

            # Create backup only if not exists
            if not backup_video.exists():
                shutil.copy2(original_video, backup_video)

            # Copy burned video to temporary file
            shutil.copy2(burned_video, replace_tmp)

            # Validate temporary file
            if not replace_tmp.exists() or replace_tmp.stat().st_size <= 0:
                self.job_store.update_job(job_id, status="failed", error="Replacement temp video missing or empty")
                raise BurnError(
                    video_path=str(original_video),
                    subtitle_path=str(ass_path),
                    reason=f"Replacement temp video is missing or empty: {replace_tmp}",
                )

            # Atomic replace
            replace_tmp.replace(original_video)

            # Validate original after replacement
            if not original_video.exists() or original_video.stat().st_size <= 0:
                self.job_store.update_job(job_id, status="failed", error="Original video replacement failed")
                raise BurnError(
                    video_path=str(original_video),
                    subtitle_path=str(ass_path),
                    reason="Original video replacement failed",
                )

            # Update output to point to original
            outputs["burned_video"] = str(original_video)

        subtitle_output = SubtitleOutput(
            ass=outputs.get("ass"),
            srt=outputs.get("srt"),
            vtt=None,
            burned_video=outputs.get("burned_video"),
        )

        metadata = SubtitleMetadata(
            language=language,
            duration=duration,
            engine="selected-transcript",
            word_timestamps=False,
        )

        # Update job to completed only after all validations and optional replace succeeded
        self.job_store.update_job(
            job_id,
            status=SubtitleJobStatus.COMPLETED.value,
            outputs=subtitle_output,
            metadata=metadata,
        )

        return {"outputs": outputs, "metadata": metadata}

    def _generate_srt_from_transcript(
        self,
        transcript: list,
        output_path,
        clip_start: float,
        opening_duration: float,
        max_duration: float,
    ) -> None:
        """Generate SRT subtitle file from transcript segments."""
        lines = []
        index = 1
        for segment in transcript:
            if not isinstance(segment, dict):
                continue
            text = segment.get("text", "")
            if not text or not isinstance(text, str) or not text.strip():
                continue
            start_val = segment.get("start")
            end_val = segment.get("end")
            if start_val is None or end_val is None:
                continue
            try:
                start = float(start_val)
                end = float(end_val)
            except (ValueError, TypeError):
                continue

            interval = self._calculate_visible_transcript_interval(
                start=start,
                end=end,
                clip_start=clip_start,
                opening_duration=opening_duration,
                max_duration=max_duration,
            )
            if interval is None:
                continue
            adjusted_start, adjusted_end = interval

            start_str = self._format_srt_timestamp(adjusted_start)
            end_str = self._format_srt_timestamp(adjusted_end)
            lines.append(str(index))
            lines.append(f"{start_str} --> {end_str}")
            lines.append(text)
            lines.append("")
            index += 1

        output_path.write_text(chr(10).join(lines), encoding="utf-8")

    def _format_ass_timestamp(self, seconds: float) -> str:
        """Format seconds to ASS timestamp (H:MM:SS.cc)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        centisecs = int((secs - int(secs)) * 100)
        return f"{hours}:{minutes:02d}:{int(secs):02d}.{centisecs:02d}"

    def _format_srt_timestamp(self, seconds: float) -> str:
        """Format seconds to SRT timestamp (HH:MM:SS,mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _get_ass_style(self, style: str) -> str:
        """Get ASS style configuration string."""
        styles = {
            "viral_clip_pro": "Inter,50,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,2,2,10,10,30,1",
            "default": "Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1",
        }
        return styles.get(style, styles["default"])


# Global instance
_package_engine: Optional[PackageEngine] = None


def get_package_engine() -> PackageEngine:
    """Get global package engine instance."""
    global _package_engine
    if _package_engine is None:
        _package_engine = PackageEngine()
    return _package_engine
