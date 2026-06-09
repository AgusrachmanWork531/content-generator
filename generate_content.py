#!/usr/bin/env python3
import os
import sys
import json
import time
import shutil
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

def wait_for_assets(source_dir: Path, video_id: str, timeout_seconds: int = 300):
    """Waits for both config JSON and thumbnail image to appear in the source directory."""
    _log_step("WAITING FOR ASSETS")
    _log(f"Please place the following files in:")
    _log(f"  {source_dir}/", color=Colors.YELLOW)
    _log(f"  1. Config JSON : {video_id}_conf.json", color=Colors.YELLOW)
    _log(f"  2. Thumbnail   : {video_id}_thumbnail.jpg (or .png)", color=Colors.YELLOW)
    _log(f"Waiting up to {timeout_seconds} seconds...")

    # Ensure source directory exists before waiting
    source_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    last_log_time = start_time
    
    config_path = None
    thumbnail_path = None
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            _log(f"Timeout! Assets not found after {timeout_seconds} seconds.", "ERROR", Colors.RED)
            return None, None

        if not config_path:
            p = source_dir / f"{video_id}_conf.json"
            if p.exists() and p.stat().st_size > 0:
                config_path = p
                _log(f"Config found: {config_path.name}", "SUCCESS", Colors.GREEN)
                
        if not thumbnail_path:
            # Check for common extensions
            for ext in ['.jpg', '.jpeg', '.png']:
                p = source_dir / f"{video_id}_thumbnail{ext}"
                if p.exists() and p.stat().st_size > 0:
                    thumbnail_path = p
                    _log(f"Thumbnail found: {thumbnail_path.name}", "SUCCESS", Colors.GREEN)
                    break

        if config_path and thumbnail_path:
            return config_path, thumbnail_path

        # Log heartbeat every 30 seconds
        if time.time() - last_log_time >= 30:
            rem = int(timeout_seconds - elapsed)
            missing = []
            if not config_path: missing.append(f"{video_id}_conf.json")
            if not thumbnail_path: missing.append(f"{video_id}_thumbnail.jpg/png")
            _log(f"Still waiting for: {', '.join(missing)}... ({rem}s remaining)")
            last_log_time = time.time()

        time.sleep(5)

def extract_video_id(source: str) -> str:
    """Extract YouTube video ID using the same logic as the bash scripts."""
    try:
        # Simple local execution of the python snippet used in bash
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
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        _log(f"Failed to extract Video ID from {source}", "ERROR", Colors.RED)
        sys.exit(1)

def cleanup_on_failure(target_dir: Path):
    _log(f"Cleaning up {target_dir}...", "CLEANUP", Colors.YELLOW)
    try:
        shutil.rmtree(target_dir)
        _log("Cleanup complete.")
    except Exception as e:
        _log(f"Cleanup failed: {e}", "WARNING")

def main():
    parser = argparse.ArgumentParser(description="Unified CLI to generate shorts content.")
    parser.add_argument("source", help="YouTube URL or Video ID")
    args = parser.parse_args()

    video_id = extract_video_id(args.source)
    _log(f"Processing Video ID: {video_id}", color=Colors.CYAN)

    # 1. Setup paths
    desktop_assets = Path.home() / "Desktop" / "assets"
    target_dir = desktop_assets / video_id
    
    source_assets_dir = Path.home() / "Downloads" / video_id
    
    # Check if target_dir exists, create if not
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        _log(f"Created output directory: {target_dir}", color=Colors.GREEN)
    else:
        _log(f"Using existing output directory: {target_dir}")

    # 2. Wait for config and thumbnail in ~/Downloads/{video_id}
    config_path, thumbnail_path = wait_for_assets(source_assets_dir, video_id)
    if not config_path or not thumbnail_path:
        cleanup_on_failure(target_dir)
        sys.exit(1)

    # Copy assets to target directory so they are bundled with the final video
    target_config = target_dir / config_path.name
    target_thumbnail = target_dir / thumbnail_path.name
    shutil.copy2(config_path, target_config)
    shutil.copy2(thumbnail_path, target_thumbnail)
    _log(f"Copied assets to {target_dir}")

    # 3. Parse config
    try:
        with open(target_config, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        _log(f"Failed to parse config JSON: {e}", "ERROR", Colors.RED)
        cleanup_on_failure(target_dir)
        sys.exit(1)

    # 4. Extract parameters from config
    try:
        payload = config.get("render_payload", {})
        crop_start = payload.get("start")
        crop_end = payload.get("end")
        opening_text = payload.get("opening_narration", {}).get("text", "")
        
        if crop_start is None or crop_end is None:
            _log("Config missing crop start/end in render_payload", "ERROR", Colors.RED)
            cleanup_on_failure(target_dir)
            sys.exit(1)
            
    except Exception as e:
        _log(f"Error extracting config parameters: {e}", "ERROR", Colors.RED)
        cleanup_on_failure(target_dir)
        sys.exit(1)

    # 5. Run backend pipeline
    _log_step("EXECUTING PIPELINE")
    
    # Build command for run.sh
    repo_root = Path(__file__).resolve().parent
    run_sh = repo_root / "run.sh"
    
    cmd = [
        str(run_sh),
        "-n", "1",
        "--skip-transcript",
        "--crop-start", str(crop_start),
        "--crop-end", str(crop_end),
        "--opening-statement", opening_text,
        "--opening-image", str(target_thumbnail),
        args.source
    ]
    
    _log(f"Running command: {' '.join(cmd)}")
    
    try:
        # Stream output in real-time
        process = subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for line in process.stdout:
            print(f"  [pipeline] {line.strip()}", flush=True)
            
        process.wait()
        
        if process.returncode != 0:
            _log(f"Pipeline failed with exit code {process.returncode}", "ERROR", Colors.RED)
            cleanup_on_failure(target_dir)
            sys.exit(1)
            
    except KeyboardInterrupt:
        _log("Pipeline interrupted by user", "WARNING", Colors.YELLOW)
        process.kill()
        process.wait()
        cleanup_on_failure(target_dir)
        sys.exit(1)
    except Exception as e:
        _log(f"Failed to execute pipeline: {e}", "ERROR", Colors.RED)
        cleanup_on_failure(target_dir)
        sys.exit(1)

    # 6. Copy final video to target dir
    _log_step("FINALIZING OUTPUT")
    
    # Find the final video in the backend storage
    # Assuming the pipeline ran successfully, the final watermarked video should be in:
    # storage/free-viral-shorts/{video_id}/watermarked/
    watermark_dir = repo_root / "storage" / "free-viral-shorts" / video_id / "watermarked"
    
    if not watermark_dir.exists():
        _log(f"Watermarked output directory not found: {watermark_dir}", "ERROR", Colors.RED)
        sys.exit(1)
        
    final_videos = list(watermark_dir.glob("short_*.mp4"))
    if not final_videos:
        _log("No final video found in watermarked directory", "ERROR", Colors.RED)
        sys.exit(1)
        
    # Sort by modification time, newest first
    final_videos.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    source_video_path = final_videos[0]
    
    # Destination path in desktop
    dest_video_path = target_dir / f"{video_id}_final.mp4"
    
    _log(f"Copying final video from {source_video_path} to {dest_video_path}...")
    shutil.copy2(source_video_path, dest_video_path)
    
    _log_step("PIPELINE COMPLETED SUCCESSFULLY")
    _log(f"Output Directory : {target_dir}", color=Colors.GREEN)
    _log(f"Final Video      : {dest_video_path.name}", color=Colors.GREEN)
    _log(f"Config File      : {target_config.name}", color=Colors.GREEN)
    _log(f"Thumbnail Image  : {target_thumbnail.name}", color=Colors.GREEN)

if __name__ == "__main__":
    main()
