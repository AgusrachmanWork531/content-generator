import os
import uuid
import re
import subprocess
import yt_dlp
import logging
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from static_ffmpeg import add_paths
    add_paths()
except ImportError:
    pass


def extract_video_id(url: str) -> str:
    """Helper to extract YouTube video ID."""
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"(?:embed\/)([0-9A-Za-z_-]{11})",
        r"(?:youtu\.be\/)([0-9A-Za-z_-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match: return match.group(1)
    
    # Fallback: If not a URL, assume it's a filename or ID
    # Remove file extension and path if present
    base = os.path.basename(url)
    name_only = os.path.splitext(base)[0]
    # Sanitize: limit to a reasonable length and characters
    clean_name = re.sub(r'[^0-9A-Za-z_-]', '_', name_only)
    return clean_name if clean_name else str(uuid.uuid4())


def download_youtube_clip(url: str, start_time: Optional[str] = None, end_time: Optional[str] = None) -> str:
    """
    Downloads the YouTube video or uses local cache in tmp_downloads/full_video.
    Returns the filename (uuid-based) of the working copy in TMP_DIR.
    """
    video_id = extract_video_id(url)
    cache_path = os.path.join(settings.FULL_VIDEO_DIR, f"{video_id}.mp4")
    
    file_id = str(uuid.uuid4())
    output_filename = f"{file_id}.mp4"
    output_path = os.path.join(settings.TMP_DIR, output_filename)
    
    os.makedirs(settings.FULL_VIDEO_DIR, exist_ok=True)
    os.environ["PATH"] = os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin"

    # ── Step 1: Check Local Cache ──
    # Check by video_id
    if os.path.exists(cache_path):
        logger.info(f"Found video {video_id} in local cache. Copying to workspace...")
        import shutil
        shutil.copy2(cache_path, output_path)
        return output_filename

    # Also check if 'url' itself is a path to a file in FULL_VIDEO_DIR
    possible_local_paths = []
    if not url.startswith("http"):
        # 1. Exact match
        possible_local_paths.append(os.path.join(settings.FULL_VIDEO_DIR, url))
        # 2. Match with auto-extensions
        for ext in ['.mp4', '.mkv', '.webm', '.MP4']:
            if not url.endswith(ext):
                possible_local_paths.append(os.path.join(settings.FULL_VIDEO_DIR, f"{url}{ext}"))

    for potential_path in possible_local_paths:
        if os.path.exists(potential_path):
            logger.info(f"Found input file {potential_path} in FULL_VIDEO_DIR. Copying...")
            import shutil
            shutil.copy2(potential_path, output_path)
            return output_filename

    # If it's not a URL and not found locally, we can't proceed
    if not url.startswith("http"):
        logger.error(f"Input '{url}' is not a valid URL and was not found in {settings.FULL_VIDEO_DIR}")
        raise ValueError(f"Input '{url}' is not a URL and not found in local cache.")

    # ── Step 2: Attempt Download ──
    # Ensure Node.js is in PATH for yt-dlp to solve JS challenges
    node_path = "/opt/homebrew/bin"
    if node_path not in os.environ["PATH"]:
        os.environ["PATH"] = f"{node_path}:{os.environ['PATH']}"
    
    logger.info(f"Current PATH for yt-dlp: {os.environ['PATH']}")

    ydl_opts = {
        'format': f'bestvideo[height<={settings.PREFERRED_RESOLUTION}]+bestaudio/best[height<={settings.PREFERRED_RESOLUTION}]/best',
        'outtmpl': output_path,
        'merge_output_format': 'mp4',
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
        'quiet': False, # Set to False for better debugging in logs
        'no_warnings': False,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'cookiesfrombrowser': ('chrome',),
        'retries': 5,
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'tv_downgraded'],
                'po_token_provider': 'bgutil:script',
                'remote_components': 'ejs:github',
            }
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Starting download for: {url}")
            ydl.download([url])

            if os.path.exists(output_path):
                # Save to cache for future use
                import shutil
                logger.info(f"Saving downloaded video to cache: {cache_path}")
                shutil.copy2(output_path, cache_path)
                
                # Check resolution
                import cv2
                cap = cv2.VideoCapture(output_path)
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
                logger.info(f"Downloaded video resolution: {w}x{h}")
                return output_filename
            else:
                raise Exception("File was not created after download.")

    except Exception as e:
        # ── Step 3: Emergency Fallback ──
        # Check one last time if it was manually placed in cache while we were trying
        if os.path.exists(cache_path):
            logger.warning(f"Download failed but found {video_id} in cache. Using cache fallback.")
            import shutil
            shutil.copy2(cache_path, output_path)
            return output_filename
            
        if os.path.exists(output_path):
            os.remove(output_path)
        logger.error(f"Failed to obtain video {video_id}: {e}")
        raise e


def _parse_time_to_seconds(time_val) -> float:
    """Convert time value (float seconds or HH:MM:SS string) to float seconds."""
    if time_val is None:
        return 0.0
    if isinstance(time_val, (int, float)):
        return float(time_val)
    
    t_str = str(time_val).strip()
    
    # Handle AM/PM format (e.g., 12:15:20 AM)
    is_pm = 'PM' in t_str.upper()
    is_am = 'AM' in t_str.upper()
    t_str = re.sub(r'\s*(AM|PM)', '', t_str, flags=re.IGNORECASE).strip()
    
    # Parse HH:MM:SS or MM:SS
    parts = t_str.split(":")
    parts = [float(p) for p in parts]
    
    seconds = 0.0
    if len(parts) == 3:
        h, m, s = parts
        # If AM/PM is present, 12 AM is 0, 12 PM is 12 (then add 12 if PM and h < 12)
        if is_am or is_pm:
            if h == 12: h = 0
            if is_pm: h += 12
        seconds = h * 3600 + m * 60 + s
    elif len(parts) == 2:
        seconds = parts[0] * 60 + parts[1]
    else:
        try:
            seconds = float(t_str)
        except ValueError:
            logger.error(f"Failed to parse time value: {time_val}")
            seconds = 0.0
        
    return seconds


def crop_video(input_path: str, output_path: str, start_time, end_time) -> str:
    """
    Crops (trims) a video using FFmpeg with fast seek.
    Uses -ss before -i for input seeking + -to for precise end point.
    Returns output_path on success.
    """
    os.environ["PATH"] = os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin"

    start_sec = _parse_time_to_seconds(start_time)
    end_sec = _parse_time_to_seconds(end_time)
    duration = end_sec - start_sec

    if duration <= 0:
        raise ValueError(f"Invalid crop range: start={start_time} end={end_time} (duration={duration}s)")

    # ── Phase 2: Frame-Accurate Crop ──
    # We use re-encoding (-c:v libx264) to ensure the crop starts EXACTLY at start_sec.
    # 'stream copy' (-c copy) is fast but snaps to the nearest preceding keyframe, 
    # which causes subtitle timing misalignment.
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "superfast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        output_path
    ]

    logger.info(f"Cropping video: {start_time} → {end_time} (duration={duration:.1f}s)")
    logger.info(f"FFmpeg cmd: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg crop failed: {result.stderr}")
        raise Exception(f"FFmpeg crop failed: {result.stderr[-500:]}")

    if not os.path.exists(output_path):
        raise Exception("Cropped file was not created.")

    logger.info(f"Crop complete: {output_path}")
    return output_path


def concat_segments(segment_paths: list[str], output_path: str) -> str:
    """
    Concatenates multiple video segments losslessly using FFmpeg concat demuxer.
    Assumes all segments have identical streams (same codec, resolution, etc.).
    """
    if not segment_paths:
        raise ValueError("No segments provided for concatenation.")

    # Create a temporary file list for ffmpeg concat
    list_path = output_path + ".txt"
    with open(list_path, "w") as f:
        for path in segment_paths:
            # Handle absolute paths correctly for ffmpeg
            abs_path = os.path.abspath(path)
            f.write(f"file '{abs_path}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path
    ]

    logger.info(f"Stitching {len(segment_paths)} segments...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Stitching complete: {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Stitching failed: {e.stderr}")
        raise Exception(f"FFmpeg stitching failed: {e.stderr[-500:]}")
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)

    return output_path
