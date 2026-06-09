#!/usr/bin/env python3
"""Script to add missing generate_from_transcript_burn method to PackageEngine."""

import os

# Read the original file first
with open('subtitle_service/package_engine.py', 'r') as f:
    content = f.read()

# Find the target location
target = '\n\n\n# Global instance'
if target not in content:
    print("ERROR: Could not find target string!")
    os._exit(1)

# Create new methods - using triple quotes to avoid escape issues
new_methods = '''

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
        self._generate_ass_from_transcript(
            transcript=selected_transcript,
            output_path=ass_path,
            clip_start=clip_start,
            opening_duration=opening_duration,
            style=style,
        )

        if not ass_path.exists():
            self.job_store.update_job(job_id, status="failed", error="ASS file not generated")
            raise UnknownSubtitleError("ASS file was not generated")

        # Also generate SRT
        srt_path = job_dir / "subtitle.srt"
        try:
            self._generate_srt_from_transcript(
                transcript=selected_transcript,
                output_path=srt_path,
                clip_start=clip_start,
                opening_duration=opening_duration,
            )
        except Exception:
            pass

        # Burn subtitle
        burned_video = None
        can_burn, burn_reason = self.ffmpeg.can_burn_subtitles()

        if can_burn:
            try:
                output_video = job_dir / "video_subtitled.mp4"
                burned_video = self.ffmpeg.burn_subtitle(
                    video_path=resolved_path,
                    subtitle_path=ass_path,
                    output_path=output_video,
                )
            except Exception:
                pass

        outputs = {
            "ass": str(ass_path) if ass_path.exists() else None,
            "srt": str(srt_path) if srt_path.exists() else None,
            "burned_video": str(burned_video) if burned_video else None,
        }

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

        self.job_store.update_job(
            job_id,
            status="completed",
            outputs=subtitle_output,
            metadata=metadata,
        )

        return {"outputs": outputs, "metadata": metadata}

    def _generate_ass_from_transcript(
            self,
            transcript: list,
            output_path,
            clip_start: float,
            opening_duration: float,
            style: str,
    ) -> None:
        """Generate ASS subtitle file from transcript segments."""
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

            adjusted_start = max(0.0, start - clip_start + opening_duration)
            adjusted_end = max(adjusted_start + 0.1, end - clip_start + opening_duration)

            start_str = self._format_ass_timestamp(adjusted_start)
            end_str = self._format_ass_timestamp(adjusted_end)
            # Escape backslashes and newlines for ASS format
            text_escaped = text.replace(chr(92), chr(92)+chr(92)).replace(chr(10), chr(92)+"N")

            lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{text_escaped}")

        output_path.write_text(chr(10).join(lines), encoding="utf-8")

    def _generate_srt_from_transcript(
            self,
            transcript: list,
            output_path,
            clip_start: float,
            opening_duration: float,
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

            adjusted_start = max(0.0, start - clip_start + opening_duration)
            adjusted_end = max(adjusted_start + 0.1, end - clip_start + opening_duration)

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

# Global instance'''

# Build new content
new_content = content.replace(target, new_methods, 1)

# Write back
with open('subtitle_service/package_engine.py', 'w') as f:
    f.write(new_content)

print("Successfully added methods!")
