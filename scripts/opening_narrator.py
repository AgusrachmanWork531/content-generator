import os
import uuid
import logging
import asyncio
import subprocess
import random
import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

try:
    from auto_thumbnail import generate_thumbnail as generate_auto_thumbnail
except Exception:
    generate_auto_thumbnail = None

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


async def _get_video_duration(video_path: str) -> float:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return max(0.0, float(stdout.decode().strip()))
    except Exception as e:
        logger.warning(f"ffprobe video duration failed: {e}")
        return 0.0


async def _get_video_size(video_path: str) -> tuple[int, int]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            video_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        width, height = [int(part) for part in stdout.decode().strip().split("x", 1)]
        return width, height
    except Exception as e:
        logger.warning(f"ffprobe video size failed, using 1080x1920: {e}")
        return 1080, 1920


async def _generate_local_tts(narration_text: str, output_path: str) -> bool:
    """Fallback for offline runs when Edge-TTS cannot reach the network."""
    async def valid_audio(path: str) -> bool:
        return Path(path).exists() and Path(path).stat().st_size > 1024 and await _get_audio_duration(path) > 0.1

    say_bin = shutil.which("say")
    tmp_aiff = str(Path(output_path).with_suffix(".aiff"))
    if say_bin:
        say_cmd = [say_bin, "--file-format=AIFF", "-o", tmp_aiff, narration_text]
        say_result = await asyncio.to_thread(subprocess.run, say_cmd, capture_output=True, text=True)
        if say_result.returncode == 0 and Path(tmp_aiff).exists():
            convert_cmd = ["ffmpeg", "-y", "-i", tmp_aiff, "-c:a", "libmp3lame", "-b:a", "128k", output_path]
            convert_result = await asyncio.to_thread(subprocess.run, convert_cmd, capture_output=True, text=True)
            _remove_quietly(tmp_aiff)
            if convert_result.returncode == 0 and await valid_audio(output_path):
                logger.info("[OpeningNarrator] Local macOS say fallback succeeded")
                return True
            logger.warning(f"[OpeningNarrator] Local TTS conversion failed: {convert_result.stderr}")
        else:
            logger.warning(f"[OpeningNarrator] macOS say fallback failed: {say_result.stderr}")

    estimated_duration = max(2.5, min(7.0, len(narration_text.split()) * 0.34))
    silent_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", f"{estimated_duration:.2f}",
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        output_path,
    ]
    silent_result = await asyncio.to_thread(subprocess.run, silent_cmd, capture_output=True, text=True)
    if silent_result.returncode == 0 and Path(output_path).exists():
        logger.warning("[OpeningNarrator] Using silent fallback audio for opening narration")
        return True
    logger.error(f"[OpeningNarrator] Silent fallback failed: {silent_result.stderr}")
    return False


async def generate_opening_video(
    narration_text: str,
    tmp_dir: str,
    thumbnail_path: str = None,
    voice: str = "id-ID-GadisNeural",
    rate: str = "+10%",
    pitch: str = "+0Hz",
    bgm_path: str = None,
    bgm_volume: float = 0.30,
    target_width: int = 1080,
    target_height: int = 1920,
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
        logger.warning(f"[OpeningNarrator] Edge-TTS failed, trying local fallback: {e}")
        if not await _generate_local_tts(narration_text, tts_path):
            return False, None

    duration = await _get_audio_duration(tts_path)
    cmd = ["ffmpeg", "-y"]

    if thumbnail_path and os.path.exists(thumbnail_path):
        cmd += ["-loop", "1", "-i", thumbnail_path]
        vf = f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,crop={target_width}:{target_height},setsar=1"
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c=black:s={target_width}x{target_height}:r=30"]
        vf = f"scale={target_width}:{target_height},setsar=1"

    cmd += ["-i", tts_path]
    if bgm_path and Path(bgm_path).exists():
        cmd += ["-stream_loop", "-1", "-i", bgm_path]
        volume = max(0.0, min(1.0, float(bgm_volume or 0.30)))
        filter_complex = (
            f"[0:v]{vf}[v];"
            f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=1.0[narr];"
            f"[2:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={volume:.3f},"
            f"afade=t=in:st=0:d=0.25,afade=t=out:st={max(0.0, duration - 0.35):.3f}:d=0.35[bgm];"
            f"[narr][bgm]amix=inputs=2:duration=first:weights=1 1:normalize=0[a]"
        )
        cmd += [
            "-t", str(duration),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-r", "30",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            opening_video_path,
        ]
    else:
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
    if result.returncode != 0:
        logger.error(f"[OpeningNarrator] Opening ffmpeg failed: {result.stderr}")
        return False, None
    return True, opening_video_path


def _read_highlights(run_path: Path) -> list[dict]:
    result_path = run_path / "result.json"
    if not result_path.exists():
        return []
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    highlights = payload.get("highlights") or []
    return highlights if isinstance(highlights, list) else []


def _clip_index_from_stem(stem: str) -> int | None:
    try:
        return int(stem.rsplit("_", 1)[-1])
    except Exception:
        return None


def _highlight_for_short(highlights: list[dict], stem: str) -> dict:
    index = _clip_index_from_stem(stem)
    if index and 0 < index <= len(highlights):
        item = highlights[index - 1]
        return item if isinstance(item, dict) else {}
    return {}


def _highlight_time(item: dict, *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except Exception:
            continue
        if number >= 0:
            return number
    return None


def _remove_quietly(path: str | Path | None) -> None:
    if not path:
        return
    try:
        target = Path(path)
        if target.exists():
            target.unlink()
    except Exception:
        pass


def _cleanup_previous_opening_artifacts(opening_dir: Path) -> None:
    patterns = [
        "opening_*.mp4",
        "opening_plan.json",
        "short_*_thumb.jpg",
        "short_*_auto_thumbnail.jpg",
        "short_*_auto_thumbnail.json",
        "short_*_opening_title.jpg",
        "short_*_opening_title.json",
        "short_*_original.mp4",
        "short_*_with_opening.mp4",
        "sfx_*.mp3",
    ]
    for pattern in patterns:
        for path in opening_dir.glob(pattern):
            _remove_quietly(path)


async def merge_opening_and_short(
    opening_video_path: str,
    short_video_path: str,
    output_path: str,
    model_name: str = None
) -> bool:
    target_width, target_height = await _get_video_size(short_video_path)
    target_fps = 30
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


async def _extract_thumbnail(short_path: str, thumbnail_path: str) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "0.8",
        "-i",
        short_path,
        "-frames:v",
        "1",
        thumbnail_path,
    ]
    result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)
    return result.returncode == 0 and os.path.exists(thumbnail_path)


async def apply_opening_to_run_dir(
    run_dir: str,
    narration_text: str,
    voice: str = "id-ID-GadisNeural",
    rate: str = "+10%",
    pitch: str = "+0Hz",
    image_path: str = None,
    thumbnail_title: str = "",
    thumbnail_talents: Iterable[str] = (),
    source_video: str = None,
    thumbnail_font_path: str = None,
    upload_title: str = "",
    source_title: str = "",
    bgm_path: str = None,
    bgm_volume: float = 0.30,
) -> dict:
    run_path = Path(run_dir)
    shorts_dir = run_path / "shorts"
    opening_dir = run_path / "opening"
    opening_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_previous_opening_artifacts(opening_dir)

    logger.info(f"Applying opening to run_dir: {run_dir}")
    logger.info(f"  narration: {narration_text[:50]}...")
    logger.info(f"  voice: {voice}, rate: {rate}, pitch: {pitch}")

    shorts = sorted(shorts_dir.glob("short_*.mp4"))
    highlights = _read_highlights(run_path)
    results = []

    if not narration_text.strip():
        return {
            "status": "skipped",
            "reason": "empty_narration_text",
            "processed_count": 0,
            "results": [],
        }

    for short_path in shorts:
        stem = short_path.stem
        thumb_path = opening_dir / f"{stem}_thumb.jpg"
        merged_path = opening_dir / f"{stem}_with_opening.mp4"
        backup_path = opening_dir / f"{stem}_original.mp4"
        highlight = _highlight_for_short(highlights, stem)
        source_start = _highlight_time(highlight, "start", "start_second", "startSecond")
        source_end = _highlight_time(highlight, "end", "end_second", "endSecond")
        effective_thumbnail_title = thumbnail_title.strip() or upload_title.strip() or narration_text.strip()

        thumbnail = image_path if image_path and Path(image_path).exists() else None
        auto_thumbnail_path = None
        if thumbnail and effective_thumbnail_title and generate_auto_thumbnail:
            titled_image_path = opening_dir / f"{stem}_opening_title.jpg"
            try:
                payload = await asyncio.to_thread(
                    generate_auto_thumbnail,
                    input_path=thumbnail,
                    output_path=str(titled_image_path),
                    title=effective_thumbnail_title,
                    talents=thumbnail_talents,
                    samples=1,
                    font_path=thumbnail_font_path,
                )
                if payload.get("status") == "success" and titled_image_path.exists():
                    thumbnail = str(titled_image_path)
            except Exception as e:
                logger.warning(f"Opening title overlay failed for {thumbnail}: {e}")
        if not thumbnail and effective_thumbnail_title and generate_auto_thumbnail:
            auto_thumbnail_path = opening_dir / f"{stem}_auto_thumbnail.jpg"
            thumbnail_input = source_video if source_video and Path(source_video).exists() else str(short_path)
            try:
                payload = await asyncio.to_thread(
                    generate_auto_thumbnail,
                    input_path=thumbnail_input,
                    output_path=str(auto_thumbnail_path),
                    title=effective_thumbnail_title,
                    talents=thumbnail_talents,
                    samples=8,
                    start=source_start if thumbnail_input != str(short_path) else None,
                    end=source_end if thumbnail_input != str(short_path) else None,
                    font_path=thumbnail_font_path,
                )
                if payload.get("status") == "success" and auto_thumbnail_path.exists():
                    thumbnail = str(auto_thumbnail_path)
            except Exception as e:
                logger.warning(f"Auto thumbnail failed for {short_path}: {e}")
        if not thumbnail and await _extract_thumbnail(str(short_path), str(thumb_path)):
            thumbnail = str(thumb_path)

        target_width, target_height = await _get_video_size(str(short_path))
        ok, opening_path = await generate_opening_video(
            narration_text=narration_text,
            tmp_dir=str(opening_dir),
            thumbnail_path=thumbnail,
            voice=voice,
            rate=rate,
            pitch=pitch,
            bgm_path=bgm_path,
            bgm_volume=bgm_volume,
            target_width=target_width,
            target_height=target_height,
        )

        if not ok or not opening_path:
            results.append({
                "short": str(short_path),
                "status": "error",
                "message": "opening_video_generation_failed",
            })
            continue

        opening_duration = await _get_video_duration(opening_path)

        merged_ok = await merge_opening_and_short(
            opening_video_path=opening_path,
            short_video_path=str(short_path),
            output_path=str(merged_path),
        )

        if not merged_ok:
            _remove_quietly(merged_path)
            results.append({
                "short": str(short_path),
                "status": "error",
                "message": "opening_merge_failed",
            })
            continue

        if not merged_path.exists() or merged_path.stat().st_size == 0:
            _remove_quietly(merged_path)
            results.append({
                "short": str(short_path),
                "status": "error",
                "message": "opening_merge_output_empty",
            })
            continue

        merged_duration = await _get_video_duration(str(merged_path))
        if merged_duration <= 0:
            _remove_quietly(merged_path)
            results.append({
                "short": str(short_path),
                "status": "error",
                "message": "opening_merge_output_invalid",
            })
            continue

        if not backup_path.exists():
            short_path.replace(backup_path)
        else:
            short_path.unlink()
        merged_path.replace(short_path)
        _remove_quietly(backup_path)
        _remove_quietly(opening_path)
        if thumbnail and thumbnail != image_path:
            _remove_quietly(thumbnail)
            _remove_quietly(Path(thumbnail).with_suffix(".json"))
        _remove_quietly(thumb_path)

        results.append({
            "short": str(short_path),
            "status": "success",
            "source_video": source_video,
            "source_start": source_start,
            "source_end": source_end,
            "opening_duration": opening_duration,
        })

        if highlight is not None:
            highlight["opening_duration"] = opening_duration

    success_count = sum(1 for item in results if item.get("status") == "success")
    payload = {
        "status": "success" if success_count == len(shorts) else "partial",
        "processed_count": len(shorts),
        "success_count": success_count,
        "narration_text": narration_text,
        "thumbnail_title": thumbnail_title,
        "thumbnail_talents": list(thumbnail_talents or []),
        "source_video": source_video,
        "thumbnail_font_path": thumbnail_font_path,
        "upload_title": upload_title,
        "source_title": source_title,
        "bgm_path": bgm_path,
        "bgm_volume": bgm_volume,
        "results": results,
    }
    try:
        result_path = run_path / "result.json"
        if result_path.exists() and highlights:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            data["highlights"] = highlights
            shorts_payload = data.get("shorts")
            if isinstance(shorts_payload, list):
                for idx, short_item in enumerate(shorts_payload):
                    if isinstance(short_item, dict) and idx < len(highlights):
                        short_item["opening_duration"] = highlights[idx].get("opening_duration")
            result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        opening_dir.rmdir()
    except OSError:
        pass
    return payload


async def render_opening_only(
    output_path: str,
    narration_text: str,
    image_path: str = None,
    voice: str = "id-ID-GadisNeural",
    rate: str = "+10%",
    pitch: str = "+0Hz",
) -> dict:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output.parent / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image = image_path if image_path and Path(image_path).exists() else None
    ok, opening_path = await generate_opening_video(
        narration_text=narration_text,
        tmp_dir=str(tmp_dir),
        thumbnail_path=image,
        voice=voice,
        rate=rate,
        pitch=pitch,
    )

    if not ok or not opening_path:
        return {
            "status": "error",
            "message": "opening_video_generation_failed",
            "output": str(output),
            "image": image,
        }

    shutil.move(opening_path, output)
    payload = {
        "status": "success",
        "mode": "opening_only",
        "output": str(output),
        "image": image,
        "narration_text": narration_text,
        "voice": voice,
        "rate": rate,
        "pitch": pitch,
    }
    (output.parent / f"{output.stem}_plan.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    # Setup logging at the very start
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stdout
    )
    
    parser = argparse.ArgumentParser(description="Generate opening narration video or prepend it to rendered shorts.")
    parser.add_argument("run_dir", nargs="?", help="Run directory containing shorts/short_*.mp4")
    parser.add_argument("--text", required=True, help="Opening narration text")
    parser.add_argument("--image", help="Optional image path used as opening visual")
    parser.add_argument("--output", help="Render opening narration only to this MP4 path")
    parser.add_argument("--voice", default="id-ID-GadisNeural")
    parser.add_argument("--rate", default="+10%")
    parser.add_argument("--pitch", default="+0Hz")
    parser.add_argument("--thumbnail-title", default="", help="Manual title for auto thumbnail generated from short frames.")
    parser.add_argument("--thumbnail-talent", action="append", default=[], help="Manual talent name for auto thumbnail label. Repeat or comma-separate.")
    parser.add_argument("--source-video", help="Original source video for auto thumbnail frame extraction.")
    parser.add_argument("--thumbnail-font", help="TTF/OTF font path for opening thumbnail title and talent labels.")
    parser.add_argument("--upload-title", default="", help="Upload title used as thumbnail title fallback.")
    parser.add_argument("--source-title", default="", help="Source title label shown at top-left of generated thumbnail.")
    parser.add_argument("--bgm", default="", help="Optional background music path mixed under opening narration.")
    parser.add_argument("--bgm-volume", type=float, default=0.30)
    args = parser.parse_args()

    # Show arguments in log
    logger.info("Starting opening narrator generation...")
    logger.info(f"  text: {args.text}")
    if args.run_dir:
        logger.info(f"  run_dir: {args.run_dir}")
    if args.output:
        logger.info(f"  output (opening only): {args.output}")
        payload = asyncio.run(
            render_opening_only(
                output_path=args.output,
                narration_text=args.text,
                image_path=args.image,
                voice=args.voice,
                rate=args.rate,
                pitch=args.pitch,
            )
        )
    else:
        if not args.run_dir:
            parser.error("run_dir is required unless --output is provided")
        payload = asyncio.run(
            apply_opening_to_run_dir(
                run_dir=args.run_dir,
                narration_text=args.text,
                voice=args.voice,
                rate=args.rate,
                pitch=args.pitch,
                image_path=args.image,
                thumbnail_title=args.thumbnail_title,
                thumbnail_talents=args.thumbnail_talent,
                source_video=args.source_video,
                thumbnail_font_path=args.thumbnail_font,
                upload_title=args.upload_title,
                source_title=args.source_title,
                bgm_path=args.bgm,
                bgm_volume=args.bgm_volume,
            )
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
