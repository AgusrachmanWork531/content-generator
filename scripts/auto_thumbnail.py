#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

# Setup logging for CLI
logger = logging.getLogger(__name__)


TARGET_SIZE = (1080, 1920)
TITLE_COLORS = ("#fff8e8", "#ffd22f")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TITLE_MAX_WIDTH_RATIO = 0.72
TITLE_MAX_HEIGHT_RATIO = 0.42
TITLE_SIDE_SAFE = 140
TITLE_STROKE = 8
TITLE_SHADOW_STROKE = 10
TITLE_LINE_GAP = 12
FONT_ALIASES = {
    "doughsy": "assets/font/doughsy-font/Doughsy-zrBq4.ttf",
    "sheeping cats": "assets/font/sheeping-cats-font/SheepingCats-929Z.ttf",
    "shepping cats": "assets/font/sheeping-cats-font/SheepingCats-929Z.ttf",
    "sheeping cats straight": "assets/font/sheeping-cats-font/SheepingCatsStraight-lrlZ.ttf",
    "sheeping cats straignt": "assets/font/sheeping-cats-font/SheepingCatsStraight-lrlZ.ttf",
    "shepping cats straight": "assets/font/sheeping-cats-font/SheepingCatsStraight-lrlZ.ttf",
    "shepping cats straignt": "assets/font/sheeping-cats-font/SheepingCatsStraight-lrlZ.ttf",
    "anton": "assets/font/thumbnail-title/Anton-Regular.ttf",
    "bangers": "assets/font/thumbnail-title/Bangers-Regular.ttf",
    "lilita one": "assets/font/thumbnail-title/LilitaOne-Regular.ttf",
    "bebas neue": "assets/font/thumbnail-title/BebasNeue-Regular.ttf",
}


@dataclass
class FrameCandidate:
    path: Path
    timestamp: float
    score: float


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def ffprobe_duration(video_path: Path) -> float:
    result = run([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    try:
        return max(0.1, float(result.stdout.strip()))
    except ValueError as exc:
        raise RuntimeError("Could not read video duration") from exc


def sample_timestamps(duration: float, count: int, start: float | None = None, end: float | None = None) -> list[float]:
    count = max(1, min(12, count))
    start_bound = 0.0 if start is None else max(0.0, min(duration, float(start)))
    end_bound = duration if end is None else max(start_bound + 0.1, min(duration, float(end)))
    if count == 1:
        return [min(start_bound + (end_bound - start_bound) * 0.42, max(0.05, end_bound - 0.05))]
    if start is None and end is None:
        start_bound = min(0.5, duration * 0.08)
        end_bound = max(start_bound, duration * 0.9)
    return [start_bound + (end_bound - start_bound) * i / (count - 1) for i in range(count)]


def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> bool:
    result = run([
        "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ])
    return result.returncode == 0 and output_path.exists()


def image_score(image_path: Path) -> float:
    with Image.open(image_path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        small = image.resize((180, 320))
        gray = ImageOps.grayscale(small)
        stat = ImageStat.Stat(gray)
        contrast = stat.stddev[0]
        brightness = stat.mean[0]
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edges)
        sharpness = edge_stat.mean[0]
        center = gray.crop((45, 64, 135, 256))
        center_contrast = ImageStat.Stat(center).stddev[0]
        brightness_penalty = abs(brightness - 135) * 0.12
        return contrast * 1.8 + sharpness * 1.2 + center_contrast * 1.1 - brightness_penalty


def pick_best_frame(video_path: Path, work_dir: Path, samples: int, start: float | None = None, end: float | None = None) -> FrameCandidate:
    duration = ffprobe_duration(video_path)
    candidates: list[FrameCandidate] = []
    for index, timestamp in enumerate(sample_timestamps(duration, samples, start=start, end=end), start=1):
        frame_path = work_dir / f"frame_{index:02d}.jpg"
        if not extract_frame(video_path, timestamp, frame_path):
            continue
        candidates.append(FrameCandidate(frame_path, timestamp, image_score(frame_path)))
    if not candidates:
        raise RuntimeError("No thumbnail frame could be extracted")
    return max(candidates, key=lambda item: item.score)


def crop_to_target(image: Image.Image, focus_y: float = 0.45) -> Image.Image:
    source_w, source_h = image.size
    target_w, target_h = TARGET_SIZE
    source_ratio = source_w / source_h
    target_ratio = target_w / target_h

    if source_ratio > target_ratio:
        crop_w = int(source_h * target_ratio)
        x0 = max(0, min(source_w - crop_w, (source_w - crop_w) // 2))
        box = (x0, 0, x0 + crop_w, source_h)
    else:
        crop_h = int(source_w / target_ratio)
        y0 = int((source_h - crop_h) * focus_y)
        y0 = max(0, min(source_h - crop_h, y0))
        box = (0, y0, source_w, y0 + crop_h)

    return image.crop(box).resize(TARGET_SIZE, Image.Resampling.LANCZOS)


def resolve_font_path(font_path: str | None = None) -> Path | None:
    if not font_path:
        return None
    raw = str(font_path).strip()
    if not raw:
        return None
    alias = FONT_ALIASES.get(raw.lower())
    candidates = [alias] if alias else []
    candidates.append(raw)
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        probes = [path] if path.is_absolute() else [Path.cwd() / path, PROJECT_ROOT / path]
        for probe in probes:
            if probe.exists() and probe.suffix.lower() in {".ttf", ".otf"}:
                return probe
    return None


def find_font(size: int, font_path: str | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    resolved_font = resolve_font_path(font_path)
    if resolved_font:
        return ImageFont.truetype(str(resolved_font), size=size)
    candidates = [
        "assets/font/doughsy-font/Doughsy-zrBq4.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def wrap_text(text: str, font: ImageFont.ImageFont, draw: ImageDraw.ImageDraw, max_width: int) -> list[str]:
    words = [word.strip() for word in text.upper().split() if word.strip()]
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        probe = word if not current else f"{current} {word}"
        if draw.textbbox((0, 0), probe, font=font, stroke_width=TITLE_STROKE)[2] <= max_width:
            current = probe
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_title(text: str, draw: ImageDraw.ImageDraw, max_width: int, max_height: int, font_path: str | None = None) -> tuple[ImageFont.ImageFont, list[str]]:
    for size in range(132, 34, -4):
        font = find_font(size, font_path=font_path)
        lines = wrap_text(text, font, draw, max_width)
        if not lines:
            continue
        boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=TITLE_STROKE) for line in lines]
        height = sum(box[3] - box[1] for box in boxes) + (len(lines) - 1) * TITLE_LINE_GAP
        if height <= max_height and all(box[2] - box[0] <= max_width for box in boxes):
            return font, lines
    font = find_font(34, font_path=font_path)
    return font, wrap_text(text, font, draw, max_width)


def draw_center_title(image: Image.Image, title: str, font_path: str | None = None) -> dict:
    draw = ImageDraw.Draw(image)
    max_width = int(TARGET_SIZE[0] * TITLE_MAX_WIDTH_RATIO)
    max_height = int(TARGET_SIZE[1] * TITLE_MAX_HEIGHT_RATIO)
    font, lines = fit_title(title, draw, max_width, max_height, font_path=font_path)
    if not lines:
        return {"lines": [], "line_count": 0, "font_size": None}

    metrics = [draw.textbbox((0, 0), line, font=font, stroke_width=TITLE_STROKE) for line in lines]
    block_height = sum(box[3] - box[1] for box in metrics) + (len(lines) - 1) * TITLE_LINE_GAP
    y = int(TARGET_SIZE[1] * 0.5 - block_height / 2)

    overlay = Image.new("RGBA", TARGET_SIZE, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        (TITLE_SIDE_SAFE - 28, y - 30, TARGET_SIZE[0] - TITLE_SIDE_SAFE + 28, y + block_height + 38),
        radius=22,
        fill=(95, 0, 0, 72),
    )
    image.alpha_composite(overlay)
    draw = ImageDraw.Draw(image)

    for index, (line, box) in enumerate(zip(lines, metrics)):
        width = box[2] - box[0]
        x = int((TARGET_SIZE[0] - width) / 2 - box[0])
        min_x = TITLE_SIDE_SAFE - box[0]
        max_x = TARGET_SIZE[0] - TITLE_SIDE_SAFE - box[2]
        x = max(min_x, min(x, max_x))
        color = TITLE_COLORS[index % len(TITLE_COLORS)]
        draw.text((x + 5, y + 7), line, font=font, fill="#6b0000", stroke_width=TITLE_SHADOW_STROKE, stroke_fill="#6b0000")
        draw.text((x, y), line, font=font, fill=color, stroke_width=TITLE_STROKE, stroke_fill="#050505")
        y += (box[3] - box[1]) + TITLE_LINE_GAP
    return {
        "lines": lines,
        "line_count": len(lines),
        "font_size": getattr(font, "size", None),
        "max_width": max_width,
        "max_height": max_height,
    }


def parse_talents(values: Iterable[str]) -> list[str]:
    talents: list[str] = []
    for value in values:
        for item in str(value).split(","):
            name = item.strip()
            if name:
                talents.append(name.upper())
    return talents[:4]


def draw_talents(image: Image.Image, talents: list[str], font_path: str | None = None) -> None:
    if not talents:
        return
    draw = ImageDraw.Draw(image)
    text = "   |   ".join(talents[:4])
    max_width = TARGET_SIZE[0] - 120
    font = find_font(42, font_path=font_path)
    for size in range(42, 25, -2):
        font = find_font(size, font_path=font_path)
        box = draw.textbbox((0, 0), text, font=font, stroke_width=3)
        if box[2] - box[0] <= max_width:
            break
    box = draw.textbbox((0, 0), text, font=font, stroke_width=3)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = (TARGET_SIZE[0] - width) // 2
    y = 82
    overlay = Image.new("RGBA", TARGET_SIZE, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(
        (max(36, x - 28), y - 14, min(TARGET_SIZE[0] - 36, x + width + 28), y + height + 22),
        radius=14,
        fill=(0, 0, 0, 82),
    )
    image.alpha_composite(overlay)
    draw.text((x, y - box[1]), text, font=font, fill="#ffe15a", stroke_width=3, stroke_fill="#070707")


def draw_source_label(image: Image.Image, source_title: str) -> None:
    text = str(source_title or "").strip()
    if not text:
        return
    draw = ImageDraw.Draw(image)
    font = find_font(34, font_path="assets/font/thumbnail-title/Anton-Regular.ttf")
    max_width = TARGET_SIZE[0] - 180
    words = text.split()
    label = ""
    for word in words:
        probe = word if not label else f"{label} {word}"
        if draw.textbbox((0, 0), probe, font=font)[2] <= max_width:
            label = probe
        else:
            break
    if not label:
        label = text[:28]
    if label != text:
        label = f"{label.rstrip()}..."

    icon_w, icon_h = 54, 38
    padding_x, padding_y = 18, 12
    text_box = draw.textbbox((0, 0), label, font=font)
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]
    x, y = 42, 48
    box_w = padding_x * 3 + icon_w + text_w
    box_h = max(icon_h, text_h) + padding_y * 2

    overlay = Image.new("RGBA", TARGET_SIZE, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle((x, y, x + box_w, y + box_h), radius=18, fill=(0, 0, 0, 118))
    icon_x = x + padding_x
    icon_y = y + (box_h - icon_h) // 2
    od.rounded_rectangle((icon_x, icon_y, icon_x + icon_w, icon_y + icon_h), radius=9, fill=(255, 0, 0, 235))
    tri = [
        (icon_x + 21, icon_y + 10),
        (icon_x + 21, icon_y + icon_h - 10),
        (icon_x + icon_w - 14, icon_y + icon_h // 2),
    ]
    od.polygon(tri, fill=(255, 255, 255, 245))
    image.alpha_composite(overlay)
    draw = ImageDraw.Draw(image)
    text_x = icon_x + icon_w + padding_x
    text_y = y + (box_h - text_h) // 2 - text_box[1]
    draw.text((text_x, text_y), label.upper(), font=font, fill="#ffffff", stroke_width=2, stroke_fill="#050505")


def add_visual_treatment(image: Image.Image) -> Image.Image:
    image = ImageEnhance.Color(image).enhance(1.12)
    image = ImageEnhance.Contrast(image).enhance(1.16)
    image = ImageEnhance.Sharpness(image).enhance(1.18)
    overlay = Image.new("RGBA", TARGET_SIZE, (0, 0, 0, 0))
    mask = Image.new("L", TARGET_SIZE, 0)
    draw = ImageDraw.Draw(mask)
    inset = 80
    draw.ellipse((-inset, -120, TARGET_SIZE[0] + inset, TARGET_SIZE[1] + 120), fill=255)
    vignette = Image.new("RGBA", TARGET_SIZE, (0, 0, 0, 90))
    overlay = Image.composite(Image.new("RGBA", TARGET_SIZE, (0, 0, 0, 0)), vignette, mask)
    image = image.convert("RGBA")
    image.alpha_composite(overlay)
    return image


def generate_thumbnail(
    input_path: str,
    output_path: str,
    title: str,
    talents: Iterable[str] = (),
    samples: int = 8,
    start: float | None = None,
    end: float | None = None,
    font_path: str | None = None,
    source_title: str | None = None,
) -> dict:
    resolved_font = resolve_font_path(font_path)

    if not title.strip():
        raise ValueError("Thumbnail title wajib diisi manual.")

    source = Path(input_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="auto_thumbnail_") as tmp:
        work_dir = Path(tmp)
        if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            frame_path = source
            timestamp = None
            score = None
        else:
            candidate = pick_best_frame(source, work_dir, samples, start=start, end=end)
            frame_path = candidate.path
            timestamp = candidate.timestamp
            score = candidate.score

        with Image.open(frame_path) as raw:
            base = ImageOps.exif_transpose(raw).convert("RGB")
        thumbnail = crop_to_target(base)
        thumbnail = add_visual_treatment(thumbnail)
        title_layout = draw_center_title(thumbnail, title, font_path=str(resolved_font) if resolved_font else font_path)
        talent_list = parse_talents(talents)
        draw_talents(thumbnail, talent_list, font_path=str(resolved_font) if resolved_font else font_path)
        thumbnail.convert("RGB").save(output, quality=94, optimize=True)

    payload = {
        "status": "success",
        "input": str(source),
        "output": str(output),
        "title": title,
        "rendered_title_lines": title_layout.get("lines", []),
        "rendered_title_line_count": title_layout.get("line_count", 0),
        "rendered_title_font_size": title_layout.get("font_size"),
        "talents": talent_list,
        "selected_timestamp": timestamp,
        "source_start": start,
        "source_end": end,
        "font_path": str(resolved_font) if resolved_font else font_path,
        "source_title": source_title,
        "selected_score": None if score is None else round(float(score), 3),
        "rules": "auto-thumbnail.md",
    }
    plan_path = output.with_suffix(".json")
    plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    # Setup logging at the start
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stdout
    )
    
    parser = argparse.ArgumentParser(description="Generate viral entertainment thumbnail from a short video or frame.")
    parser.add_argument("--input", required=True, help="Short video or image/frame path.")
    parser.add_argument("--output", required=True, help="Output JPG/PNG path.")
    parser.add_argument("--title", required=True, help="Manual thumbnail title. The script does not invent this.")
    parser.add_argument("--talent", action="append", default=[], help="Manual talent name. Repeat or comma-separate.")
    parser.add_argument("--samples", type=int, default=8, help="Number of video frames to evaluate.")
    parser.add_argument("--start", type=float, help="Start second when input is a source video.")
    parser.add_argument("--end", type=float, help="End second when input is a source video.")
    parser.add_argument("--font", help="TTF/OTF font path. Defaults to the existing thumbnail fallback font.")
    parser.add_argument("--source-title", help="Deprecated. Source credit belongs in the main video, not the thumbnail.")
    args = parser.parse_args()

    logger.info("Starting auto thumbnail generation...")
    logger.info(f"  input: {args.input}")
    logger.info(f"  output: {args.output}")
    logger.info(f"  title: {args.title}")
    logger.info(f"  samples: {args.samples}")
    
    payload = generate_thumbnail(
        input_path=args.input,
        output_path=args.output,
        title=args.title,
        talents=args.talent,
        samples=args.samples,
        start=args.start,
        end=args.end,
        font_path=args.font,
        source_title=args.source_title,
    )
    
    # Log result status
    if payload.get("status") == "success":
        logger.info(f"Thumbnail generated successfully")
        logger.info(f"  output: {payload.get('output')}")
        logger.info(f"  title_lines: {payload.get('rendered_title_line_count', 0)}")
        logger.info(f"  talents: {len(payload.get('talents', []))}")
    else:
        logger.error(f"Thumbnail generation failed: {payload.get('error', 'unknown error')}")
    
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
