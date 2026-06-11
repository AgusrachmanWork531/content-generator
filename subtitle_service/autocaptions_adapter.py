"""
AutoCaptions Adapter for subtitle service.

Primary subtitle engine using auto-captions external package.
Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.

Uses external auto-captions package:
- caption_generator.py: Extract audio and transcribe with Whisper
- json_to_ass.py: Convert word timestamps to styled ASS

This adapter wraps the package without copying source code.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

from .config import get_settings, get_subtitle_style
from .errors import PackageNotInstalledError, PackageExecutionError


# ASS tag pattern to strip for text length calculation
ASS_TAG_PATTERN = re.compile(r'\{[^}]*\}')


class AutoCaptionsAdapter:
    """AutoCaptions wrapper for subtitle generation."""

    def __init__(self):
        self.settings = get_settings()
        self._auto_captions_path: Optional[str] = None

    def check_installed(self) -> bool:
        """Check if auto-captions is installed."""
# Check if the external package directory exists and has required scripts
        package_dir = self._get_package_dir()
        if package_dir and package_dir.exists():
            generator_script = package_dir / "caption_generator.py"
            ass_script = package_dir / "json_to_ass.py"
            return generator_script.exists() and ass_script.exists()
        return False

    def ensure_installed(self):
        """Ensure auto-captions is installed."""
        if not self.check_installed():
            raise PackageNotInstalledError("auto-captions")

    def _python_can_import(self, python_bin: str, module_name: str) -> bool:
        """
        Check if a Python binary can import a specific module.
        
        Args:
            python_bin: Path to Python binary
            module_name: Module name to check (e.g., 'whisper')
            
        Returns:
            True if the module can be imported, False otherwise
        """
        if not python_bin:
            return False
        
        # Check if executable exists or is discoverable
        import shutil
        if not os.path.isfile(python_bin) and not shutil.which(python_bin):
            return False
        
        try:
            result = subprocess.run(
                [python_bin, "-c", f"import {module_name}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _resolve_auto_captions_python(self) -> str:
        """
        Resolve the Python binary for running auto-captions.
        
        Priority order:
        1. SUBTITLE_AUTOCAPTIONS_PYTHON env var
        2. VENV_DIR/bin/python
        3. CV_PYTHON_BIN env var
        4. sys.executable
        5. python3
        
        Returns:
            Path to valid Python binary that can import whisper
            
        Raises:
            PackageExecutionError: If no valid Python can import whisper
        """
        import shutil
        
        candidates = []
        
        # 1. SUBTITLE_AUTOCAPTIONS_PYTHON env var
        subtitle_python = os.environ.get("SUBTITLE_AUTOCAPTIONS_PYTHON")
        if subtitle_python:
            candidates.append(("SUBTITLE_AUTOCAPTIONS_PYTHON", subtitle_python))
        
        # 2. VENV_DIR/bin/python
        venv_dir = os.environ.get("VENV_DIR")
        if venv_dir:
            venv_python = Path(venv_dir) / "bin" / "python"
            candidates.append(("VENV_DIR", str(venv_python)))
        
        # 3. CV_PYTHON_BIN env var
        cv_python = os.environ.get("CV_PYTHON_BIN")
        if cv_python:
            candidates.append(("CV_PYTHON_BIN", cv_python))
        
        # 4. sys.executable
        candidates.append(("sys.executable", sys.executable))
        
        # 5. python3
        candidates.append(("python3", "python3"))
        
        # Try each candidate until one can import whisper
        for name, python_bin in candidates:
            if self._python_can_import(python_bin, "whisper"):
                print(f"[AutoCaptions] Using {name} for auto-captions: {python_bin}")
                return python_bin
        
        # None of the candidates worked
        raise PackageExecutionError(
            package_name="auto-captions",
            command="resolve auto-captions python",
            returncode=-1,
stderr="Auto-captions Python environment missing whisper. Set SUBTITLE_AUTOCAPTIONS_PYTHON=/path/to/python or install openai-whisper into VENV_DIR.",
        )

    def _get_package_dir(self) -> Optional[Path]:
        """Get the auto-captions package directory."""
        # Try multiple possible locations
        possible_paths = [
            Path(__file__).parent.parent / "external_packages" / "auto-captions",
            Path("external_packages/auto-captions"),
        ]

        for path in possible_paths:
            if path.exists():
                return path
        return None

    @property
    def package_dir(self) -> Path:
        """Get the auto-captions package directory."""
        pkg_dir = self._get_package_dir()
        if pkg_dir is None:
            raise PackageNotInstalledError("auto-captions")
        return pkg_dir

    def _run_caption_generator(
        self,
        input_video: Path,
        output_dir: Path,
        language: str = "id",
        model: str = "medium",
        preset: str = "accurate",
        initial_prompt: str = "",
        corrections_file: Optional[str] = None,
        audio_preset: Optional[str] = None,
    ) -> Path:
        """
        Run caption_generator.py to produce word timestamps JSON.
        
        Returns path to the generated word_timestamps.json.
        """
        self.ensure_installed()
        output_dir.mkdir(parents=True, exist_ok=True)

        # FIX: Convert to absolute paths to ensure output goes to correct location
        # The script runs with cwd=package_dir, so relative paths would resolve incorrectly
        audio_path = (output_dir / "audio.wav").resolve()
        json_path = (output_dir / "word_timestamps.json").resolve()
        
        # Also ensure input_video is absolute path
        input_video_abs = input_video.resolve()

        # Resolve Python binary that has whisper
        python_bin = self._resolve_auto_captions_python()

        # Build Python command to run the generator script
        cmd = [
            python_bin,
            str(self.package_dir / "caption_generator.py"),
            "-i", str(input_video_abs),
            "-a", str(audio_path),
            "-o", str(json_path),
            "-m", model,
            "-l", language,
            "--preset", preset,
        ]
        if initial_prompt:
            cmd.extend(["--initial-prompt", initial_prompt])
        if corrections_file:
            cmd.extend(["--corrections-file", str(Path(corrections_file).resolve())])
        if audio_preset:
            cmd.extend(["--audio-preset", audio_preset])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minutes
            # FIX: Remove cwd to avoid relative path resolution issues
            # The script will now use absolute paths for all file operations
            cwd=str(self.package_dir),
        )

        if result.returncode != 0:
            raise PackageExecutionError(
                package_name="auto-captions",
                command=" ".join(cmd),
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        if not json_path.exists():
            raise PackageExecutionError(
                package_name="auto-captions",
                command=" ".join(cmd),
                returncode=-1,
                stdout=result.stdout,
                stderr=f"Output file not generated: {json_path}",
            )

        return json_path

    def _run_json_to_ass(
        self,
        json_path: Path,
        output_path: Path,
        words_per_cap: int = 2,
        font: str = "Montserrat Black",
        fontsize: int = 82,
        outline: int = 9,
        shadow: int = 1,
        margin_v: int = 480,
        margin_lr: int = 120,
        color_active: str = "#FFCC00",
        color_inactive: str = "#E0E0E0",
        outline_color: str = "#000000",
        uppercase: bool = True,
        max_chars_per_caption: int = 16,
        tail_hold: float = 0.12,
        pop_in_ms: int = 50,
        pop_out_ms: int = 120,
        pop_outline_extra: int = 4,
        pop_blur: float = 0.5,
        fsp: float = 3.0,
        use_scale_animation: bool = False,
        per_word_popup: bool = True,
    ) -> Path:
        """
        Run json_to_ass.py to convert word timestamps to ASS.
        
        Returns path to the generated ASS file.
        """
        self.ensure_installed()

        # Convert to absolute paths to ensure output goes to correct location
        json_path_abs = json_path.resolve()
        output_path_abs = output_path.resolve()

        # Resolve Python binary that has whisper
        python_bin = self._resolve_auto_captions_python()

        # Build Python command to run the ASS converter
        cmd = [
            python_bin,
            str(self.package_dir / "json_to_ass.py"),
            "--json", str(json_path_abs),
            "--out", str(output_path_abs),
            "--words-per-cap", str(words_per_cap),
            "--font", font,
            "--fontsize", str(fontsize),
            "--outline", str(outline),
            "--shadow", str(shadow),
            "--margin-v", str(margin_v),
            "--margin-lr", str(margin_lr),
            "--active", color_active,
            "--inactive", color_inactive,
            "--outline-color", outline_color,
            "--max-chars-per-caption", str(max_chars_per_caption),
            "--tail-hold", str(tail_hold),
            "--pop-in-ms", str(pop_in_ms),
            "--pop-out-ms", str(pop_out_ms),
            "--pop-outline-extra", str(pop_outline_extra),
            "--pop-blur", str(pop_blur),
            "--fsp", str(fsp),
        ]

        if not uppercase:
            cmd.append("--no-uppercase")
        
        if use_scale_animation:
            cmd.append("--use-scale-animation")

        if per_word_popup:
            cmd.append("--per-word-popup")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(self.package_dir),
        )

        if result.returncode != 0:
            raise PackageExecutionError(
                package_name="auto-captions",
                command=" ".join(cmd),
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        if not output_path.exists():
            raise PackageExecutionError(
                package_name="auto-captions",
                command=" ".join(cmd),
                returncode=-1,
                stdout=result.stdout,
                stderr=f"Output file not generated: {output_path}",
            )

        return output_path

    def post_process_ass_style(
        self,
        ass_path: Path,
        style: str = "viral_clip_pro",
    ) -> Path:
        """
        Post-process ASS file with style adjustments.
        
        This is a placeholder for custom style processing.
        For now, it just returns the original path.
        
        Args:
            ass_path: Path to the generated ASS file
            style: Style preset name
            
        Returns:
            Path to the (possibly modified) ASS file
        """
        if not ass_path.exists():
            raise PackageExecutionError(
                package_name="auto-captions",
                command="post_process_ass_style",
                returncode=-1,
                stdout="",
                stderr=f"ASS file not found: {ass_path}",
            )
        
        # For now, just return the original path
        # Future: Could apply style-specific modifications here
        return ass_path

    def transcribe(
        self,
        input_video: Path,
        output_dir: Path,
        language: str = "id",
        transcribe_model: str = "medium",
        transcribe_preset: str = "accurate",
        initial_prompt: str = "",
        corrections_file: Optional[str] = None,
        audio_preset: Optional[str] = None,
    ) -> dict:
        """
        Transcribe video to word timestamps JSON.
        
        Returns dict with:
        - word_timestamps_json: path to JSON file
        """
        self.ensure_installed()
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = self._run_caption_generator(
            input_video=input_video,
            output_dir=output_dir,
            language=language,
            model=transcribe_model,
            preset=transcribe_preset,
            initial_prompt=initial_prompt,
            corrections_file=corrections_file,
            audio_preset=audio_preset,
        )

        return {"word_timestamps_json": str(json_path)}

    def generate(
        self,
        input_video: Path,
        output_dir: Path,
        language: str = "id",
        style: str = "viral_clip_pro",
        output_formats: list[str] = None,
        burn: bool = False,
        transcribe_model: str = "medium",
        transcribe_preset: str = "accurate",
        initial_prompt: str = "",
        corrections_file: Optional[str] = None,
        audio_preset: Optional[str] = None,
        full_word_timestamps: Optional[str] = None,
        clip_start: float = 0.0,
        clip_end: float = 0.0,
    ) -> dict:
        """Generate subtitles using auto-captions.
        
        This is the main entry point for subtitle generation.
        Returns output file paths.
        
        Args:
            input_video: Path to input video
            output_dir: Directory for output files
            language: Language code
            style: Style preset name
            output_formats: List of desired output formats (ass, srt, vtt)
            burn: Whether to burn subtitles ( handled elsewhere)
            
        Returns:
            dict with output file paths
        """
        if output_formats is None:
            output_formats = ["ass"]

        self.ensure_installed()
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get style configuration
        style_config = get_subtitle_style(style)

        # Step 1: Generate word timestamps
        json_path = output_dir / "word_timestamps.json"
        
        if full_word_timestamps and os.path.exists(full_word_timestamps):
            print(f"[AutoCaptions] Using cached full video word timestamps: {full_word_timestamps}")
            import json
            try:
                with open(full_word_timestamps, "r", encoding="utf-8") as f:
                    full_words = json.load(f)
                
                sliced_words = []
                for w in full_words:
                    mid = (w["start"] + w["end"]) / 2
                    if clip_start <= mid <= clip_end:
                        w_copy = dict(w)
                        w_copy["start"] = max(0.0, w["start"] - clip_start)
                        w_copy["end"] = max(w_copy["start"] + 0.01, w["end"] - clip_start)
                        sliced_words.append(w_copy)
                
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(sliced_words, f, ensure_ascii=False, indent=2)
                print(f"[AutoCaptions] Sliced {len(sliced_words)} words for clip range [{clip_start:.2f}, {clip_end:.2f}]")
            except Exception as e:
                print(f"[AutoCaptions] Error slicing full timestamps: {e}. Falling back to Whisper.")
                json_path = self._run_caption_generator(
                    input_video=input_video,
                    output_dir=output_dir,
                    language=language,
                    model=transcribe_model,
                    preset=transcribe_preset,
                    initial_prompt=initial_prompt,
                    corrections_file=corrections_file,
                    audio_preset=audio_preset,
                )
        else:
            json_path = self._run_caption_generator(
                input_video=input_video,
                output_dir=output_dir,
                language=language,
                model=transcribe_model,
                preset=transcribe_preset,
                initial_prompt=initial_prompt,
                corrections_file=corrections_file,
                audio_preset=audio_preset,
            )

        outputs = {}

        # Step 2: Generate ASS if requested
        if "ass" in output_formats:
            ass_path = output_dir / "captions.ass"
            self._run_json_to_ass(
                json_path=json_path,
                output_path=ass_path,
                words_per_cap=style_config["words_per_cap"],
                font=style_config["font"],
                fontsize=style_config["fontsize"],
                outline=style_config["outline"],
                shadow=style_config["shadow"],
                margin_v=style_config["margin_v"],
                margin_lr=style_config["margin_lr"],
                color_active=style_config["active"],
                color_inactive=style_config["inactive"],
                outline_color=style_config["outline_color"],
                uppercase=True,
                max_chars_per_caption=style_config["max_chars_per_caption"],
                tail_hold=style_config["tail_hold"],
                pop_in_ms=style_config["pop_in_ms"],
                pop_out_ms=style_config["pop_out_ms"],
                pop_outline_extra=style_config["pop_outline_extra"],
                pop_blur=style_config["pop_blur"],
                fsp=style_config.get("fsp", 3.0),
                use_scale_animation=style_config["use_scale_animation"],
                per_word_popup=style_config.get("per_word_popup", True),
            )
            outputs["ass"] = str(ass_path)

        # Step 3: Post-process ASS style
        if "ass" in outputs:
            processed_ass = self.post_process_ass_style(
                Path(outputs["ass"]),
                style=style,
            )
            outputs["ass"] = str(processed_ass)

            # Step 4: Validate ASS quality
            quality_result = self.validate_ass_quality(processed_ass)
            
            # Print warnings without failing the process
            for warning in quality_result.get("warnings", []):
                print(f"WARNING: {warning}")

        # Step 5: Generate SRT if requested (using same blocks as ASS)
        if "srt" in output_formats and "ass" in outputs:
            srt_path = output_dir / "captions.srt"
            word_json_path = Path(json_path)
            
            # Need to get word timestamps from the JSON file that was used for ASS
            # The _run_caption_generator already created it
            if word_json_path.exists():
                self._generate_srt_from_blocks(
                    json_path=word_json_path,
                    output_path=srt_path,
                    words_per_cap=style_config["words_per_cap"],
                    max_chars_per_caption=style_config["max_chars_per_caption"],
                    tail_hold=style_config["tail_hold"],
                )
                outputs["srt"] = str(srt_path)
                print(f"[AutoCaptions] SRT generated: {srt_path}")

        return outputs

    def validate_ass_quality(self, ass_path: Path) -> dict:
        """
        Validate ASS subtitle quality.
        
        Don't raise error for warnings - just collect them.
        
        Checks:
        - File exists
        - Dialogue count
        - Max chars per dialogue (after ASS tags stripped)
        - Dialogue overlap
        - Empty text
        - PlayResX = 1080
        - PlayResY = 1920
        
        Args:
            ass_path: Path to the ASS file
            
        Returns:
            dict with:
            - ok: bool (True if no critical errors)
            - warnings: list of warning strings
            - dialogue_count: int
            - max_chars: int
            - has_overlap: bool
        """
        warnings = []
        dialogue_count = 0
        max_chars = 0
        has_overlap = False
        has_empty_text = False
        playres_x_ok = True
        playres_y_ok = True

        # Check file exists
        if not ass_path.exists():
            warnings.append(f"File not found: {ass_path}")
            return {
                "ok": False,
                "warnings": warnings,
                "dialogue_count": 0,
                "max_chars": 0,
                "has_overlap": False,
            }

        # Parse ASS file
        try:
            content = ass_path.read_text(encoding="utf-8")
        except Exception as e:
            warnings.append(f"Failed to read file: {e}")
            return {
                "ok": False,
                "warnings": warnings,
                "dialogue_count": 0,
                "max_chars": 0,
                "has_overlap": False,
            }

        lines = content.split("\n")

        # Check PlayResX and PlayResY
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("PlayResX:"):
                if "1080" not in line_stripped:
                    playres_x_ok = False
                    warnings.append(f"PlayResX not 1080: {line_stripped}")
            elif line_stripped.startswith("PlayResY:"):
                if "1920" not in line_stripped:
                    playres_y_ok = False
                    warnings.append(f"PlayResY not 1920: {line_stripped}")

        # Extract dialogues
        dialogues = []
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("Dialogue:"):
                dialogues.append(line_stripped)

        dialogue_count = len(dialogues)

        if dialogue_count == 0:
            warnings.append("No dialogues found")
            return {
                "ok": True,  # Not critical, but warn
                "warnings": warnings,
                "dialogue_count": 0,
                "max_chars": 0,
                "has_overlap": False,
            }

        # Parse dialogues and check each one
        dialogue_times = []
        for i, dialogue in enumerate(dialogues):
            # Format: Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
            parts = dialogue.split(",", 9)
            if len(parts) < 10:
                continue

            start = parts[1].strip()
            end = parts[2].strip()
            text = parts[9].strip()

            # Convert time to seconds for comparison
            start_sec = self._ass_time_to_seconds(start)
            end_sec = self._ass_time_to_seconds(end)

            # Store for overlap check
            dialogue_times.append((start_sec, end_sec))

            # Clean ASS tags and check text length
            clean_text = self._clean_ass_tags(text)
            text_length = len(clean_text)

            if text_length == 0:
                has_empty_text = True
                warnings.append(f"Dialogue {i+1} has empty text")

            if text_length > max_chars:
                max_chars = text_length

        # Check for overlap
        for i in range(len(dialogue_times) - 1):
            current_end = dialogue_times[i][1]
            next_start = dialogue_times[i + 1][0]
            if current_end > next_start:
                has_overlap = True
                warnings.append(
                    f"Dialogue overlap: dialogue {i+1} ends at {current_end}s, "
                    f"dialogue {i+2} starts at {next_start}s"
                )

        # Add warnings for issues found
        if max_chars > 22:
            warnings.append(f"Max characters per dialogue: {max_chars} (limit: 22)")

        if has_overlap:
            warnings.append("Dialogue overlap detected")

        if has_empty_text:
            warnings.append("Empty dialogue text detected")

        if not playres_x_ok:
            warnings.append("PlayResX should be 1080")

        if not playres_y_ok:
            warnings.append("PlayResY should be 1920")

        # Determine if overall is OK (no critical errors, only warnings)
        ok = (
            ass_path.exists()
            and dialogue_count > 0
            and not has_empty_text
        )

        return {
            "ok": ok,
            "warnings": warnings,
            "dialogue_count": dialogue_count,
            "max_chars": max_chars,
            "has_overlap": has_overlap,
        }

    def _ass_time_to_seconds(self, time_str: str) -> float:
        """
        Convert ASS time format (H:MM:SS.CS) to seconds.
        
        Args:
            time_str: Time string like "0:00:05.25"
            
        Returns:
            Time in seconds as float
        """
        try:
            # Format: H:MM:SS.CS
            parts = time_str.split(":")
            if len(parts) != 3:
                return 0.0

            hours = int(parts[0])
            minutes = int(parts[1])
            seconds_parts = parts[2].split(".")
            seconds = int(seconds_parts[0])
            centiseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0

            total_seconds = (
                hours * 3600
                + minutes * 60
                + seconds
                + centiseconds / 100.0
            )
            return total_seconds
        except (ValueError, IndexError):
            return 0.0
    def _clean_ass_tags(self, text: str) -> str:
        r"""
        Remove ASS tags from text for length calculation.

        Args:
            text: Text with potential ASS tags like {\an8}{\c&H...}

        Returns:
            Clean text without tags
        """
        # Remove all {....} patterns
        clean = ASS_TAG_PATTERN.sub("", text)
        return clean.strip()

    def _srt_time(self, seconds: float) -> str:
        """
        Convert seconds to SRT time format (HH:MM:SS,mmm).
        
        Args:
            seconds: Time in seconds
            
        Returns:
            Time string in SRT format like "00:00:05,250"
        """
        ms = int(round(seconds * 1000))
        hours = ms // 3600000
        minutes = (ms % 3600000) // 60000
        secs = (ms % 60000) // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _generate_srt_from_blocks(
        self,
        json_path: Path,
        output_path: Path,
        words_per_cap: int = 2,
        max_chars_per_caption: int = 18,
        tail_hold: float = 0.08,
    ) -> Path:
        """
        Generate SRT file from word timestamps using same block logic as ASS.
        
        Args:
            json_path: Path to word_timestamps.json
            output_path: Path for output SRT file
            words_per_cap: Maximum words per caption block
            max_chars_per_caption: Maximum characters per caption
            tail_hold: Extra hold time in seconds
            
        Returns:
            Path to generated SRT file
        """
        import json
        
        # Load word timestamps
        words = json.loads(json_path.read_text(encoding="utf-8"))
        
        if not words:
            return output_path
        
        # Build caption blocks using same logic as json_to_ass.py
        blocks = self._build_caption_blocks_for_srt(
            words, words_per_cap, max_chars_per_caption
        )
        
        # Write SRT file
        srt_lines = []
        for idx, block in enumerate(blocks):
            # Block timing: from first word start to last word end + tail hold.
            block_start = float(block[0]["start"])
            block_end = float(block[-1]["end"]) + tail_hold
            
            # Prevent tail_hold overlap with next block
            next_block_start = None
            if idx + 1 < len(blocks):
                next_block_start = float(blocks[idx + 1][0]["start"])
            
            if next_block_start is not None and block_end > next_block_start:
                block_end = next_block_start
            
            # Ensure minimum duration only when timing data is invalid.
            if block_end <= block_start:
                if next_block_start is None:
                    block_end = block_start + 0.5
                else:
                    block_end = block_start
            
            # Build text (uppercase to match ASS default).
            text = " ".join(str(w["word"]).strip().upper() for w in block)
            
            # Format: index, time --> time, text
            srt_lines.append(str(idx + 1))
            srt_lines.append(f"{self._srt_time(block_start)} --> {self._srt_time(block_end)}")
            srt_lines.append(text)
            srt_lines.append("")  # Empty line between subtitles
        
        output_path.write_text("\n".join(srt_lines), encoding="utf-8")
        return output_path

    def _build_caption_blocks_for_srt(
        self,
        words: list,
        words_per_cap: int,
        max_chars_per_caption: int,
    ) -> list:
        """
        Build caption blocks for SRT matching ASS logic.
        
        Args:
            words: List of word dictionaries with 'word', 'start', 'end'
            words_per_cap: Maximum words per block
            max_chars_per_caption: Maximum characters per block
            
        Returns:
            List of word lists (blocks)
        """
        if not words:
            return []
        
        blocks = []
        i = 0
        n = len(words)
        
        while i < n:
            block = []
            j = i
            while j < n:
                word = str(words[j]["word"]).upper()
                word_len = len(word)
                
                if block:
                    new_word_count = len(block) + 1
                    new_char_count = len(" ".join(w["word"].upper() for w in block)) + 1 + word_len
                    
                    if new_word_count > words_per_cap:
                        break
                    if new_char_count > max_chars_per_caption:
                        break
                
                block.append(words[j])
                j += 1
            
            if not block:
                block = [words[i]]
                i += 1
            else:
                i = j
            
            blocks.append(block)
        
        return blocks


# Global instance
_auto_captions_adapter: Optional[AutoCaptionsAdapter] = None


def get_auto_captions_adapter() -> AutoCaptionsAdapter:
    """Get global auto-captions adapter instance."""
    global _auto_captions_adapter
    if _auto_captions_adapter is None:
        _auto_captions_adapter = AutoCaptionsAdapter()
    return _auto_captions_adapter
