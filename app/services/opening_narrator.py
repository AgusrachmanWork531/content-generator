import os
import uuid
import logging
import asyncio
import subprocess
import random

logger = logging.getLogger(__name__)

# 5 Model Transisi: (nama, xfade_type, xfade_dur, sfx_filter, sfx_vol)
TRANSITION_MODELS = [
    ("CROSS_FADE",    "fade",      0.5, "sine=f=200:d=0.5,afade=t=out:st=0:d=0.5", 0.4),
    ("SOFT_DISSOLVE", "dissolve",  0.6, "sine=f=300:d=0.6,afade=t=out:st=0:d=0.6", 0.4),
    ("SMOOTH_WASH",   "fade",      0.4, "sine=f=100:d=0.4,afade=t=out:st=0:d=0.4", 0.3),
]


async def _get_audio_duration(audio_path: str) -> float:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        duration = float(stdout.decode().strip())
        return duration
    except Exception as e:
        logger.warning(f"ffprobe failed, using default 3.0s: {e}")
        return 3.0


async def generate_opening_video(
    narration_text: str,
    tmp_dir: str,
    thumbnail_path: str = None,
    voice: str = "id-ID-GadisNeural",
    rate: str = "+10%",
    pitch: str = "+0Hz",
) -> tuple[bool, str]:
    uid = uuid.uuid4().hex[:8]
    tts_path = os.path.join(tmp_dir, f"opening_tts_{uid}.mp3")
    opening_video_path = os.path.join(tmp_dir, f"opening_{uid}.mp4")

    logger.info(f"[OpeningNarrator] Generating TTS: voice={voice}, rate={rate}")
    try:
        import edge_tts
        communicate = edge_tts.Communicate(
            text=narration_text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )
        await communicate.save(tts_path)
    except Exception as e:
        logger.error(f"[OpeningNarrator] Edge-TTS failed: {e}")
        return False, None

    duration = await _get_audio_duration(tts_path)
    cmd = ["ffmpeg", "-y"]

    if thumbnail_path and os.path.exists(thumbnail_path):
        cmd += ["-loop", "1", "-i", thumbnail_path]
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    else:
        cmd += ["-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30"]
        vf = "scale=1080:1920,setsar=1"

    cmd += ["-i", tts_path]
    cmd += [
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-r", "30",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        opening_video_path,
    ]

    result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)
    if os.path.exists(tts_path): os.remove(tts_path)
    if result.returncode != 0: return False, None
    return True, opening_video_path


async def merge_opening_and_short(
    opening_video_path: str,
    short_video_path: str,
    output_path: str,
    model_name: str = None
) -> bool:
    target_width, target_height, target_fps = 1080, 1920, 30
    try:
        duration_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", opening_video_path]
        proc = await asyncio.create_subprocess_exec(*duration_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = await proc.communicate()
        duration_v1 = float(stdout.decode().strip())
        
        model_data = random.choice(TRANSITION_MODELS)
        m_name, xfade_type, xfade_dur, sfx_filter, sfx_vol = model_data
        offset = max(0, duration_v1 - xfade_dur)
        
        uid = uuid.uuid4().hex[:8]
        sfx_path = os.path.join(os.path.dirname(output_path), f"sfx_{uid}.mp3")
        sfx_cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", sfx_filter, "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k", sfx_path]
        await asyncio.to_thread(subprocess.run, sfx_cmd, capture_output=True)

        filter_complex = (
            f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={target_fps}[v0];"
            f"[1:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={target_fps}[v1];"
            f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
            f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
            f"[2:a]adelay={int(offset*1000)}|{int(offset*1000)},aresample=44100[sfx];"
            f"[v0][v1]xfade=transition={xfade_type}:duration={xfade_dur}:offset={offset}[v];"
            f"[a0][a1]acrossfade=d={xfade_dur}[ax];"
            f"[ax][sfx]amix=inputs=2:weights=1 {sfx_vol}:normalize=0[a]"
        )

        merge_cmd = ["ffmpeg", "-y", "-i", opening_video_path, "-i", short_video_path, "-i", sfx_path, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "superfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", output_path]
        result = await asyncio.to_thread(subprocess.run, merge_cmd, capture_output=True, text=True)
        if os.path.exists(sfx_path): os.remove(sfx_path)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Merge error: {e}")
        return False
