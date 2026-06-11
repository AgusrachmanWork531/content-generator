#!/usr/bin/env python3
"""
Subtitle Generation CLI.

Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.

Usage:
  python scripts/generate_subtitle.py --video storage/free-viral-shorts/VIDEO_ID/clips/clip_1.mp4 --language id --engine auto-captions --formats ass,srt --burn false
  
  python scripts/generate_subtitle.py --video storage/free-viral-shorts/VIDEO_ID/clips/clip_1.mp4 --language id --engine auto-captions --burn true
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subtitle_service.config import ensure_subtitle_output_dir
from subtitle_service.package_engine import get_package_engine
from subtitle_service.job_store import get_job_store
from subtitle_service.models import SubtitleJobStatus


def main():
    parser = argparse.ArgumentParser(description="Generate subtitles for video")
    
    parser.add_argument(
        "--video", "-v",
        required=True,
        help="Path to video file (absolute or storage-relative)"
    )
    parser.add_argument(
        "--language", "-l",
        default="id",
        help="Language code (default: id)"
    )
    parser.add_argument(
        "--engine", "-e",
        default="auto-captions",
        help="Subtitle engine (default: auto-captions)"
    )
    parser.add_argument(
        "--style", "-s",
        default="viral_clip_pro",
        help="Subtitle style (default: viral_clip_pro)"
    )
    parser.add_argument(
        "--formats", "-f",
        default="ass,srt",
        help="Output formats comma-separated (default: ass,srt)"
    )
    parser.add_argument(
        "--burn", "-b",
        default="false",
        choices=["true", "false"],
        help="Burn subtitle to video (default: false)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        help="Output directory (default: storage/subtitle-jobs)"
    )
    parser.add_argument(
        "--transcribe-model",
        default="medium",
        help="Whisper model for auto-captions transcription (default: medium)"
    )
    parser.add_argument(
        "--transcribe-preset",
        default="accurate",
        choices=["fast", "accurate", "review"],
        help="Transcription quality preset (default: accurate)"
    )
    parser.add_argument(
        "--initial-prompt",
        default="",
        help="Optional Whisper initial prompt for transcription context"
    )
    parser.add_argument(
        "--corrections-file",
        default=None,
        help="Optional JSON file with transcription corrections"
    )
    parser.add_argument(
        "--audio-preset",
        default=None,
        choices=["plain", "speech"],
        help="Optional audio preprocessing preset for transcription"
    )
    parser.add_argument(
        "--replace-original",
        action="store_true",
        help="Replace original video with burned version (only when --burn true)"
    )
    parser.add_argument(
        "--full-word-timestamps",
        default=None,
        help="Optional path to full video word timestamps JSON"
    )
    parser.add_argument(
        "--clip-start",
        type=float,
        default=0.0,
        help="Clip start time offset in seconds"
    )
    parser.add_argument(
        "--clip-end",
        type=float,
        default=0.0,
        help="Clip end time offset in seconds"
    )
    
    args = parser.parse_args()
    
    # Parse formats
    output_formats = [f.strip() for f in args.formats.split(",")]
    
    # Parse burn
    burn_subtitle = args.burn.lower() == "true"
    
    # Ensure output directory exists
    ensure_subtitle_output_dir()
    
    print(f"Generating subtitles for: {args.video}")
    print(f"Language: {args.language}")
    print(f"Engine: {args.engine}")
    print(f"Formats: {output_formats}")
    print(f"Burn: {burn_subtitle}")
    print(f"Replace Original: {args.replace_original}")
    print(f"Transcribe Model: {args.transcribe_model}")
    print(f"Transcribe Preset: {args.transcribe_preset}")
    if args.corrections_file:
        print(f"Corrections File: {args.corrections_file}")
    if args.audio_preset:
        print(f"Audio Preset: {args.audio_preset}")
    print()
    
    # Get engine and job store
    engine = get_package_engine()
    job_store = get_job_store()
    
    # Create job
    job = job_store.create_job(
        video_path=args.video,
        language=args.language,
        output_formats=output_formats,
        engine=args.engine,
        style=args.style,
        burn_subtitle=burn_subtitle,
        transcribe_model=args.transcribe_model,
        transcribe_preset=args.transcribe_preset,
        initial_prompt=args.initial_prompt,
        corrections_file=args.corrections_file,
        audio_preset=args.audio_preset,
    )
    
    print(f"Job created: {job.job_id}")
    print(f"Status: {job.status}")
    print()
    
    # Generate subtitles
    try:
        if burn_subtitle and args.replace_original:
            result = engine.generate_burn(
                job_id=job.job_id,
                video_path=args.video,
                language=args.language,
                engine=args.engine,
                style=args.style,
                replace_original=True,
                transcribe_model=args.transcribe_model,
                transcribe_preset=args.transcribe_preset,
                initial_prompt=args.initial_prompt,
                corrections_file=args.corrections_file,
                audio_preset=args.audio_preset,
                full_word_timestamps=args.full_word_timestamps,
                clip_start=args.clip_start,
                clip_end=args.clip_end,
            )
        else:
            result = engine.generate(
                job_id=job.job_id,
                video_path=args.video,
                language=args.language,
                output_formats=output_formats,
                engine=args.engine,
                style=args.style,
                burn_subtitle=burn_subtitle,
                transcribe_model=args.transcribe_model,
                transcribe_preset=args.transcribe_preset,
                initial_prompt=args.initial_prompt,
                corrections_file=args.corrections_file,
                audio_preset=args.audio_preset,
                full_word_timestamps=args.full_word_timestamps,
                clip_start=args.clip_start,
                clip_end=args.clip_end,
            )

        print("Subtitle generation completed!")
        print()

        # Print outputs
        outputs = result.get("outputs", {})
        print("Outputs:")
        if outputs.get("ass"):
            print(f"  ASS: {outputs['ass']}")
        if outputs.get("srt"):
            print(f"  SRT: {outputs['srt']}")
        if outputs.get("vtt"):
            print(f"  VTT: {outputs['vtt']}")
        if outputs.get("burned_video"):
            print(f"  Burned Video: {outputs['burned_video']}")

        metadata = result.get("metadata")
        print()
        print("Metadata:")
        print(f"  Language: {metadata.language if metadata else 'N/A'}")
        print(f"  Duration: {metadata.duration if metadata else 'N/A'}s")
        print(f"  Engine: {metadata.engine if metadata else 'N/A'}")
        print(f"  Word Timestamps: {metadata.word_timestamps if metadata else 'N/A'}")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
