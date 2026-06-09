#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path
from typing import Optional

# Configuration
# Default to local repo paths, can be overridden via env vars
APP_DIR = Path(__file__).resolve().parent
STORAGE_DIR = Path(
    os.environ.get("CONTENT_SHORT_STORAGE_DIR", APP_DIR / "storage")
).resolve()
TRANSCRIPT_DIR = STORAGE_DIR / "transcripts"
VIDEO_DIR = STORAGE_DIR / "video"

# Make sure directories exist
TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

def find_downloaded_video(video_id: str) -> Optional[Path]:
    """Find the most recent downloaded video file for a given video_id.
    
    Searches VIDEO_DIR for video files matching the video_id.
    Returns the most recent non-empty file, or None if not found.
    """
    extensions = {".mp4", ".mkv", ".webm", ".mov"}
    if not VIDEO_DIR.exists():
        return None

    matches = [
        path
        for path in VIDEO_DIR.iterdir()
        if path.is_file()
        and video_id in path.name
        and path.suffix.lower() in extensions
        and path.stat().st_size > 0
    ]
    if not matches:
        return None
    
    # Sort by modification time, most recent first
    matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0]

def convert_word_timestamps_to_transcript_files(
    video_id: str,
    language: str = "id",
) -> dict:
    """Convert word_timestamps.json to all transcript file formats.
    
    Args:
        video_id: The YouTube video ID
        language: Language code for the transcript
    
    Returns:
        Dict with paths to created files
    """
    import re
    
    transcript_dir = TRANSCRIPT_DIR / video_id
    word_timestamps_path = transcript_dir / "word_timestamps.json"
    
    if not word_timestamps_path.exists():
        raise FileNotFoundError(f"word_timestamps.json not found: {word_timestamps_path}")
    
    # Load word timestamps
    word_timestamps = json.loads(word_timestamps_path.read_text())
    if not isinstance(word_timestamps, list):
        raise ValueError(f"word_timestamps.json must contain a list, got {type(word_timestamps)}")
    
    # Group words into segments of ~12 words each
    segments = []
    words_per_segment = 12
    
    for i in range(0, len(word_timestamps), words_per_segment):
        segment_words = word_timestamps[i:i + words_per_segment]
        if not segment_words:
            continue
        
        text = " ".join(w.get("word", "") for w in segment_words)
        start = segment_words[0].get("start", 0.0)
        end = segment_words[-1].get("end", 0.0)
        
        segments.append({
            "start": start,
            "end": end,
            "duration": end - start,
            "text": text,
        })
    
    # Write transcript.clean.json
    clean_path = transcript_dir / "transcript.clean.json"
    clean_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2))
    
    # Write transcript.raw.json (same as clean for now)
    raw_path = transcript_dir / "transcript.raw.json"
    raw_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2))
    
    # Write transcript.txt
    txt_path = transcript_dir / "transcript.txt"
    txt_content = "\n".join(s.get("text", "") for s in segments if s.get("text"))
    txt_path.write_text(txt_content, encoding="utf-8")
    
    # Write transcript.paragraphs.txt
    para_path = transcript_dir / "transcript.paragraphs.txt"
    para_content = "\n\n".join(s.get("text", "") for s in segments if s.get("text"))
    para_path.write_text(para_content, encoding="utf-8")
    
    # Write transcript.srt
    def format_srt_timestamp(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    
    srt_path = transcript_dir / "transcript.srt"
    srt_lines = []
    for idx, seg in enumerate(segments, 1):
        start_ts = format_srt_timestamp(seg.get("start", 0.0))
        end_ts = format_srt_timestamp(seg.get("end", 0.0))
        text = seg.get("text", "")
        srt_lines.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}\n")
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    
    # Write transcript.vtt
    vtt_path = transcript_dir / "transcript.vtt"
    def format_vtt_timestamp(seconds: float) -> str:
        minutes = int(seconds // 60)
        secs = seconds % 60
        millis = int((secs % 1) * 1000)
        return f"{minutes:02d}:{secs:06.3f}"
    
    vtt_lines = ["WEBVTT", ""]
    for seg in segments:
        start_ts = format_vtt_timestamp(seg.get("start", 0.0))
        end_ts = format_vtt_timestamp(seg.get("end", 0.0))
        text = seg.get("text", "")
        vtt_lines.append(f"{start_ts} --> {end_ts}")
        vtt_lines.append(text)
        vtt_lines.append("")
    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")
    
    # Write metadata.json
    # First language from request
    first_language = language.split(",")[0].strip() if "," in language else language.strip()
    
    metadata = {
        "source_method": "audio-whisper-fallback",
        "video_id": video_id,
        "requested_languages": language.split(","),
        "selected_transcript": {
            "video_id": video_id,
            "language_code": first_language,
            "is_generated": True,
            "is_translatable": False,
            "translated_to": None,
        }
    }
    metadata_path = transcript_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    
    return {
        "clean": clean_path,
        "raw": raw_path,
        "txt": txt_path,
        "paragraphs": para_path,
        "srt": srt_path,
        "vtt": vtt_path,
        "metadata": metadata_path,
    }
