"""
WhisperX Adapter for subtitle service.

Fallback/subtitle engine for word-level timestamps.
Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.

Uses WhisperX package for:
- transcribe
- alignment
- word-level timestamp
- language detection
- diarization (future)

This adapter uses the WhisperX package as-is without copying source code.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .config import get_settings
from .errors import PackageNotInstalledError, PackageExecutionError


class WhisperXAdapter:
    """WhisperX wrapper for subtitle generation."""

    def __init__(self):
        self.settings = get_settings()
        self._whisperx_path: Optional[str] = None

    def check_installed(self) -> bool:
        """Check if WhisperX is installed."""
        return shutil.which("whisperx") is not None or shutil.which("whisperx-cli") is not None

    def ensure_installed(self):
        """Ensure WhisperX is installed."""
        if not self.check_installed():
            raise PackageNotInstalledError("whisperx")

    @property
    def whisperx_cli(self) -> str:
        """Get WhisperX CLI command."""
        if shutil.which("whisperx"):
            return "whisperx"
        elif shutil.which("whisperx-cli"):
            return "whisperx-cli"
        return "whisperx"

    def transcribe(
        self,
        input_video: Path,
        output_dir: Path,
        language: str = "id",
        model: str = "base",
    ) -> dict:
        """
        Transcribe video using WhisperX.
        
        Returns dict with:
        - output_json: path to full JSON output
        - output_srt: path to SRT subtitle
        - output_vtt: path to VTT subtitle
        - output_ass: path to ASS subtitle (if available)
        """
        self.ensure_installed()
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build output filenames
        output_json = output_dir / "transcribe.json"
        output_srt = output_dir / "subtitle.srt"
        output_vtt = output_dir / "subtitle.vtt"

        # Build WhisperX command
        # Note: WhisperX CLI options may vary, adjust as needed
        cmd = [
            self.whisperx_cli,
            str(input_video),
            "--model", model,
            "--language", language,
            "--output_dir", str(output_dir),
            "--output_format", "all",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minutes
        )

        if result.returncode != 0:
            raise PackageExecutionError(
                package_name="whisperx",
                command=" ".join(cmd),
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        # Find generated output files
        outputs = {}
        
        # Look for JSON output
        if output_json.exists():
            outputs["output_json"] = str(output_json)
        
        # Look for SRT
        if output_srt.exists():
            outputs["output_srt"] = str(output_srt)
        
        # Look for VTT
        if output_vtt.exists():
            outputs["output_vtt"] = str(output_vtt)
        
        # Try to find any generated files
        for ext in ["*.json", "*.srt", "*.vtt", "*.ass"]:
            for f in output_dir.glob(ext):
                if f.is_file():
                    key = f"output_{f.suffix[1:]}"
                    if key not in outputs:
                        outputs[key] = str(f)

        return outputs

    def align(
        self,
        audio_path: Path,
        transcript_path: Path,
        output_path: Path,
        language: str = "id",
        model: str = "base",
    ) -> dict:
        """
        Align transcript with audio for word-level timestamps.
        
        Note: This is a placeholder - WhisperX handles alignment 
        internally during transcription.
        """
        self.ensure_installed()
        
        # For WhisperX, alignment is typically done during transcription
        # If separate alignment is needed, use the align functionality
        cmd = [
            self.whisperx_cli,
            str(audio_path),
            "--model", model,
            "--language", language,
            "--align",
            "--transcript", str(transcript_path),
            "--output", str(output_path),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            raise PackageExecutionError(
                package_name="whisperx",
                command=" ".join(cmd),
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        return {"aligned_output": str(output_path)}

    def generate(
        self,
        input_video: Path,
        output_dir: Path,
        language: str = "id",
        output_formats: list[str] = None,
    ) -> dict:
        """
        Generate subtitles using WhisperX.
        
        This is the main entry point for subtitle generation.
        Returns output file paths.
        """
        if output_formats is None:
            output_formats = ["srt", "vtt"]

        return self.transcribe(
            input_video=input_video,
            output_dir=output_dir,
            language=language,
        )


# Global instance
_whisperx_adapter: Optional[WhisperXAdapter] = None


def get_whisperx_adapter() -> WhisperXAdapter:
    """Get global WhisperX adapter instance."""
    global _whisperx_adapter
    if _whisperx_adapter is None:
        _whisperx_adapter = WhisperXAdapter()
    return _whisperx_adapter
