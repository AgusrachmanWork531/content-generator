"""
Subtitle Job Store.

Manages subtitle jobs with disk persistence.
Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.

Storage structure:
storage/subtitle-jobs/{job_id}/
  input.json
  command.log
  package_stdout.log
  package_stderr.log
  subtitle.ass
  subtitle.srt
  video_subtitled.mp4
  result.json
  error.json
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import get_settings
from .models import SubtitleJob, SubtitleJobStatus, SubtitleOutput, SubtitleMetadata


class JobStore:
    """In-memory job store with disk persistence."""

    def __init__(self):
        self.settings = get_settings()
        self.jobs: dict[str, SubtitleJob] = {}
        # Ensure output directory exists
        self.settings.subtitle_output_dir.mkdir(parents=True, exist_ok=True)

    def resolve_video_path(self, video_path: str) -> Path:
        """Resolve video path (absolute or storage-relative)."""
        path = Path(video_path)
        if not path.is_absolute():
            # Assume relative to project root
            from pathlib import Path as ProjectPath
            project_root = ProjectPath(__file__).resolve().parent.parent
            path = project_root / video_path
        return path

    def get_job_dir(self, job_id: str) -> Path:
        """Get job output directory."""
        return self.settings.subtitle_output_dir / job_id

    def create_job(
        self,
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
    ) -> SubtitleJob:
        """Create a new subtitle job."""
        job_id = str(uuid.uuid4())
        
        if output_formats is None:
            output_formats = ["ass", "srt"]

        job = SubtitleJob(
            job_id=job_id,
            status=SubtitleJobStatus.PENDING.value,
            video_path=video_path,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        self.jobs[job_id] = job
        
        # Create job directory
        job_dir = self.get_job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        
        # Save input.json
        input_data = {
            "video_path": video_path,
            "language": language,
            "output_formats": output_formats,
            "engine": engine,
            "style": style,
            "burn_subtitle": burn_subtitle,
            "transcribe_model": transcribe_model,
            "transcribe_preset": transcribe_preset,
            "initial_prompt": initial_prompt,
            "corrections_file": corrections_file,
            "audio_preset": audio_preset,
        }
        (job_dir / "input.json").write_text(
            json.dumps(input_data, ensure_ascii=False, indent=2)
        )
        
        # Save initial job state
        self._save_job_state(job_id, job)
        
        return job

    def _save_job_state(self, job_id: str, job: SubtitleJob):
        """Save job state to disk."""
        job_dir = self.get_job_dir(job_id)
        result_path = job_dir / "result.json"
        
        # Build result dict
        result = {
            "job_id": job.job_id,
            "status": job.status,
            "video_path": job.video_path,
            "outputs": None,
            "metadata": None,
            "error": job.error,
            "error_code": job.error_code,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
        }
        
        if job.outputs:
            result["outputs"] = {
                "ass": job.outputs.ass,
                "srt": job.outputs.srt,
                "vtt": job.outputs.vtt,
                "burned_video": job.outputs.burned_video,
            }
        
        if job.metadata:
            result["metadata"] = {
                "language": job.metadata.language,
                "duration": job.metadata.duration,
                "engine": job.metadata.engine,
                "word_timestamps": job.metadata.word_timestamps,
            }
        
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    def update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        outputs: Optional[SubtitleOutput] = None,
        metadata: Optional[SubtitleMetadata] = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> SubtitleJob:
        """Update job status and outputs."""
        if job_id not in self.jobs:
            raise ValueError(f"Job not found: {job_id}")
        
        job = self.jobs[job_id]
        
        if status:
            job.status = status
            if status == SubtitleJobStatus.COMPLETED.value or status == SubtitleJobStatus.FAILED.value:
                job.completed_at = datetime.now(timezone.utc).isoformat()
        
        if outputs:
            job.outputs = outputs
        
        if metadata:
            job.metadata = metadata
        
        if error:
            job.error = error
        
        if error_code:
            job.error_code = error_code
        
        # Save to disk
        self._save_job_state(job_id, job)
        
        return job

    def get_job(self, job_id: str) -> Optional[SubtitleJob]:
        """Get job by ID."""
        return self.jobs.get(job_id)

    def get_job_from_disk(self, job_id: str) -> Optional[SubtitleJob]:
        """Load job from disk."""
        job_dir = self.get_job_dir(job_id)
        result_path = job_dir / "result.json"
        
        if not result_path.exists():
            return None
        
        try:
            data = json.loads(result_path.read_text())
            
            outputs = None
            if data.get("outputs"):
                outputs_data = data["outputs"]
                outputs = SubtitleOutput(
                    ass=outputs_data.get("ass"),
                    srt=outputs_data.get("srt"),
                    vtt=outputs_data.get("vtt"),
                    burned_video=outputs_data.get("burned_video"),
                )
            
            metadata = None
            if data.get("metadata"):
                metadata_data = data["metadata"]
                metadata = SubtitleMetadata(
                    language=metadata_data.get("language", "id"),
                    duration=metadata_data.get("duration", 0.0),
                    engine=metadata_data.get("engine", "auto-captions"),
                    word_timestamps=metadata_data.get("word_timestamps", False),
                )
            
            job = SubtitleJob(
                job_id=data.get("job_id", job_id),
                status=data.get("status", "pending"),
                video_path=data.get("video_path", ""),
                outputs=outputs,
                metadata=metadata,
                error=data.get("error"),
                error_code=data.get("error_code"),
                created_at=data.get("created_at"),
                completed_at=data.get("completed_at"),
            )
            
            return job
        
        except Exception:
            return None

    def save_command_log(
        self,
        job_id: str,
        command: str,
        stdout: str = "",
        stderr: str = "",
    ):
        """Save command execution logs."""
        job_dir = self.get_job_dir(job_id)
        
        # Save command
        (job_dir / "command.log").write_text(command)
        
        # Save stdout/stderr
        if stdout:
            (job_dir / "package_stdout.log").write_text(stdout)
        
        if stderr:
            (job_dir / "package_stderr.log").write_text(stderr)

    def save_error(self, job_id: str, error_data: dict):
        """Save error information."""
        job_dir = self.get_job_dir(job_id)
        (job_dir / "error.json").write_text(
            json.dumps(error_data, ensure_ascii=False, indent=2)
        )

    def save_ffmpeg_log(
        self,
        job_id: str,
        version: str = "",
        filters: str = "",
        command: str = "",
        stderr: str = "",
    ):
        """Save FFmpeg command logs for debugging."""
        job_dir = self.get_job_dir(job_id)
        
        if version:
            (job_dir / "ffmpeg_version.log").write_text(version)
        
        if filters:
            (job_dir / "ffmpeg_filters.log").write_text(filters)
        
        if command:
            (job_dir / "ffmpeg_command.log").write_text(command)
        
        if stderr:
            (job_dir / "ffmpeg_stderr.log").write_text(stderr)


# Global job store instance
_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """Get global job store instance."""
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store
