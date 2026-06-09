#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    RESET = '\033[0m'

def _log(msg: str, level: str = "INFO", color: str = ""):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = f"[{ts}] [{level}] "
    if color:
        print(f"{color}{prefix}{msg}{Colors.RESET}", flush=True)
    else:
        print(f"{prefix}{msg}", flush=True)

def _log_step(step_name: str):
    print(f"\n{Colors.CYAN}={'='*50}{Colors.RESET}", flush=True)
    _log(f"STEP: {step_name}", level="STEP", color=Colors.CYAN)
    print(f"{Colors.CYAN}={'='*50}{Colors.RESET}", flush=True)

def extract_video_id(source: str) -> str:
    cmd = ["python3", "-c", """
import sys, re; from urllib.parse import parse_qs, urlparse
value = sys.argv[1].strip()
if re.fullmatch(r"[A-Za-z0-9_-]{11}", value): print(value); sys.exit(0)
parsed = urlparse(value); host = parsed.netloc.lower().replace("www.", "")
parts = [p for p in parsed.path.split("/") if p]
if host == "youtu.be" and parts: print(parts[0][:11]); sys.exit(0)
q_id = parse_qs(parsed.query).get("v", [None])[0]
if q_id: print(q_id[:11]); sys.exit(0)
if host.endswith("youtube.com") and parts and parts[0] in {"shorts", "embed", "live"} and len(parts) > 1: print(parts[1][:11]); sys.exit(0)
match = re.search(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", value)
if match: print(match.group(1)); sys.exit(0)
sys.exit(1)
    """, source]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        _log(f"Failed to extract Video ID from {source}", "ERROR", Colors.RED)
        sys.exit(1)

def run_command_with_streaming(cmd, cwd=None):
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    for line in process.stdout:
        print(f"  [pipeline] {line.strip()}", flush=True)
    process.wait()
    return process.returncode

def main():
    parser = argparse.ArgumentParser(description="Standalone Transcription CLI")
    parser.add_argument("source", help="YouTube URL or Video ID")
    parser.add_argument("--languages", default="id,en", help="Language codes for transcription (e.g. id,en)")
    args = parser.parse_args()

    video_id = extract_video_id(args.source)
    _log(f"Processing Transcription for Video ID: {video_id}", color=Colors.CYAN)
    
    repo_root = Path(__file__).resolve().parent
    transcript_dir = repo_root / "storage" / "transcripts" / video_id
    output_json_path = transcript_dir / "transcript.clean.json"
    
    # 1. Check if video is downloaded
    _log_step("VIDEO DOWNLOAD (REQUIRED FOR FALLBACK)")
    sys.path.insert(0, str(repo_root))
    from transcript_utils import find_downloaded_video
    
    if not find_downloaded_video(video_id):
        _log("Video not found locally. Downloading now...")
        cmd_download = [
            str(repo_root / "tools" / "youtube" / "download_youtube_hd.sh"),
            "-q", "1080",
            args.source
        ]
        if run_command_with_streaming(cmd_download, cwd=str(repo_root)) != 0:
            _log("Video download failed. Fallback might not work.", "WARNING", Colors.YELLOW)
    else:
        _log("Video already downloaded.", "SUCCESS", Colors.GREEN)

    # 2. Try youtube-transcript-api extraction
    _log_step("YOUTUBE CAPTION EXTRACTION")
    if output_json_path.exists() and output_json_path.stat().st_size > 0:
        _log(f"Transcript already exists at {output_json_path}", "SUCCESS", Colors.GREEN)
    else:
        cmd_transcript = [
            str(repo_root / "tools" / "youtube" / "transcribe_youtube.sh"),
            "-o", str(repo_root / "storage" / "transcripts"),
            "-l", args.languages,
            args.source
        ]
        _log("Running youtube-transcript-api extraction...")
        run_command_with_streaming(cmd_transcript, cwd=str(repo_root))

    # 3. Fallback to Whisper
    if not (output_json_path.exists() and output_json_path.stat().st_size > 0):
        _log_step("WHISPER AUDIO FALLBACK")
        _log("YouTube captions failed or missing. Running Whisper local transcription...")
        
        video_path = find_downloaded_video(video_id)
        if not video_path:
            _log("Could not find downloaded video for Whisper fallback.", "ERROR", Colors.RED)
            sys.exit(1)
        
        _log(f"Using video file: {video_path}")
        
        try:
            # We call the fallback logic directly to get the format right
            from transcript_utils import convert_word_timestamps_to_transcript_files
            
            _log("Starting run_audio_fallback_transcription (logs will be explicit)...")
            
            cmd_whisper = [
                str(repo_root / "tools" / "audio" / "transcribe_audio_whisper.sh"),
                "-o", str(repo_root / "storage" / "transcripts"),
                "-l", args.languages.split(',')[0],
                str(video_path)
            ]
            
            _log(f"Running Whisper Command: {' '.join(cmd_whisper)}")
            retcode = run_command_with_streaming(cmd_whisper, cwd=str(repo_root))
            
            if retcode != 0:
                _log("Whisper transcription process failed.", "ERROR", Colors.RED)
                sys.exit(1)
                
            _log("Converting word timestamps to clean format...")
            convert_word_timestamps_to_transcript_files(
                video_id=video_id,
                language=args.languages.split(',')[0]
            )
            
        except Exception as e:
            _log(f"Whisper fallback exception: {e}", "ERROR", Colors.RED)
            sys.exit(1)

    # 4. Final Verification and Copy
    _log_step("FINALIZING RESULT")
    if not output_json_path.exists() or output_json_path.stat().st_size == 0:
        _log("Failed to generate transcript output.", "ERROR", Colors.RED)
        sys.exit(1)
        
    downloads_dir = Path.home() / "Downloads" / video_id
    downloads_dir.mkdir(parents=True, exist_ok=True)
    final_output_path = downloads_dir / f"{video_id}_transcribe.json"
    
    _log(f"Copying RAW JSON to {final_output_path}...")
    import shutil
    shutil.copy2(output_json_path, final_output_path)
    
    _log("TRANSCRIPTION PIPELINE COMPLETE", "SUCCESS", Colors.GREEN)
    _log(f"Result available at: {final_output_path}", "SUCCESS", Colors.GREEN)

if __name__ == "__main__":
    main()
