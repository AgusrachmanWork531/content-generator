"""
Captions Adapter for subtitle format conversion.

Optional fallback package for subtitle format handling.
Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.

Uses captions package only for read/write/convert/validate subtitle format.
Do not create parser/converter manually if package can handle.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .config import get_settings
from .errors import PackageNotInstalledError, PackageExecutionError


class CaptionsAdapter:
    """Captions package wrapper for format conversion."""

    def __init__(self):
        self.settings = get_settings()
        self._captions_path: Optional[str] = None

    def check_installed(self) -> bool:
        """Check if captions is installed."""
        return shutil.which("captions") is not None

    def ensure_installed(self):
        """Ensure captions is installed."""
        if not self.check_installed():
            raise PackageNotInstalledError("captions")

    @property
    def captions_cli(self) -> str:
        """Get captions CLI command."""
        return "captions"

    def convert(
        self,
        input_path: Path,
        output_path: Path,
        input_format: str = None,
        output_format: str = None,
    ) -> dict:
        """
        Convert subtitle between formats.
        
        Supported formats: srt, vtt, ass, ssa, txt
        """
        self.ensure_installed()

        # Determine formats from extensions
        if input_format is None:
            input_format = input_path.suffix[1:]
        if output_format is None:
            output_format = output_path.suffix[1:]

        # Build captions command
        cmd = [
            self.captions_cli,
            "convert",
            "-i", str(input_path),
            "-o", str(output_path),
        ]

        if input_format:
            cmd.extend(["--from", input_format])
        if output_format:
            cmd.extend(["--to", output_format])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise PackageExecutionError(
                package_name="captions",
                command=" ".join(cmd),
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        return {"output": str(output_path)}

    def validate(self, subtitle_path: Path, format: str = None) -> bool:
        """
        Validate subtitle file format.
        
        Returns True if valid, False otherwise.
        """
        self.ensure_installed()

        if format is None:
            format = subtitle_path.suffix[1:]

        cmd = [
            self.captions_cli,
            "validate",
            str(subtitle_path),
            "--format", format,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        return result.returncode == 0

    def to_srt(self, input_path: Path, output_path: Path) -> Path:
        """Convert subtitle to SRT format."""
        result = self.convert(input_path, output_path, output_format="srt")
        return Path(result["output"])

    def to_vtt(self, input_path: Path, output_path: Path) -> Path:
        """Convert subtitle to VTT format."""
        result = self.convert(input_path, output_path, output_format="vtt")
        return Path(result["output"])

    def to_ass(self, input_path: Path, output_path: Path) -> Path:
        """Convert subtitle to ASS format."""
        result = self.convert(input_path, output_path, output_format="ass")
        return Path(result["output"])


# Global instance
_captions_adapter: Optional[CaptionsAdapter] = None


def get_captions_adapter() -> CaptionsAdapter:
    """Get global captions adapter instance."""
    global _captions_adapter
    if _captions_adapter is None:
        _captions_adapter = CaptionsAdapter()
    return _captions_adapter
