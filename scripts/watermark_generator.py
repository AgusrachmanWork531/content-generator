#!/usr/bin/env python3
"""
Professional Watermark Generator for Clipper Engine

Purpose:
- Adaptive watermark placement from crop_plan/layout_variant/subject_side.
- Professional badge/logo/text watermark.
- Wide-context and split-safe awareness.
- Updates result.json with watermark_plan and watermarked_file.
- Fail-loud by default so failed watermark render is not mistaken as success.

Main fixes:
- Do not silently return original input_file as watermarked_file when FFmpeg fails.
- Fix FFmpeg font path escaping outside f-string expression.
- Avoid double opacity on logo assets.
- Make dry-run non-error.
- Store watermark_error when rendering fails.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# Setup logging for CLI
logger = logging.getLogger(__name__)


DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,

    # auto, safe_badge, split_safe, logo, text
    "mode": "text",

    # Default branding.
    # For KILASAN VIDEO logo mode, pass --logo or config.logo_path.
    "text": "@KilasanVideo",
    "logo_path": None,

    # Font / badge.
    "font_path": str(Path(__file__).resolve().parents[1] / "assets/font/doughsy-font/Doughsy-zrBq4.ttf"),
    "font_size": 64,
    "font_color": [255, 255, 255, 255],
    "text_box": False,
    "text_shadow": True,
    "text_shadow_color": "black@0.45",
    "text_shadow_offset": [2, 2],
    "source_title": "",
    "source_prefix": "Source: ",
    "source_font_size": 34,
    "source_opacity": 0.74,
    "source_margin_x": 42,
    "source_margin_y": 72,
    "badge_bg_color": [0, 0, 0, 92],
    "badge_radius": 18,
    "badge_padding_x": 22,
    "badge_padding_y": 12,
    "badge_gap": 12,
    "badge_shadow": True,
    "badge_shadow_offset": [0, 3],
    "badge_shadow_color": [0, 0, 0, 80],

    # Logo sizing.
    # For 1080x1920 watermark: 80-120 is usually visible.
    "logo_height": 110,

    # Opacity is applied in FFmpeg overlay.
    # Logo/image asset itself is kept full-alpha to avoid double-opacity.
    "logo_opacity": 0.72,
    "opacity": 0.72,
    "split_opacity": 0.58,

    # Position.
    "position": "center_15_top",
    "default_position": "top_right",
    "split_position": "center_top",
    "center_top_ratio": 0.15,
    "safe_margin_x": 48,
    "safe_margin_y": 72,

    # Subtitle avoidance.
    "avoid_subtitle_zone": True,
    "subtitle_zone_y_min_ratio": 0.66,
    "subtitle_zone_y_max_ratio": 0.94,

    # Render.
    "video_codec": "libx264",
    "audio_codec": "copy",
    "crf": 18,
    "preset": "veryfast",
    "pix_fmt": "yuv420p",
    "overwrite": True,

    # Telegram Bot API uploads are safest below 50 MB. Keep a buffer for
    # multipart overhead and downstream proxy limits.
    "telegram_delivery_enabled": True,
    "telegram_target_mb": 45,
    "telegram_audio_bitrate": "128k",
    "telegram_min_video_bitrate_kbps": 800,
    "telegram_max_video_bitrate_kbps": 3600,

    # Important:
    # False = failed watermark render becomes error, not original file.
    # True  = pipeline may continue, but watermarked_file is still not marked as success.
    "fail_soft": False,
}

CLIP_PATH_KEYS = [
    "watermarked_file",
    "final_video_file",
    "rendered_file",
    "clip_path",
    "clip_url",
    "clip_file",
    "output_file",
    "video_file",
    "file",
    "path",
]


@dataclass
class VideoMeta:
    width: int
    height: int
    fps: Optional[str]
    duration: float


@dataclass
class WatermarkPlan:
    clip_index: int
    enabled: bool
    mode: str
    position: str
    reason: str
    input_file: Optional[str]
    output_file: Optional[str]
    asset_file: Optional[str]
    overlay_x: str
    overlay_y: str
    opacity: float
    layout: Optional[str]
    layout_variant: Optional[str]
    subject_side: Optional[str]
    frame_width: int
    frame_height: int
    duration: float
    ffmpeg_filter: Optional[str] = None
    ffmpeg_command: Optional[str] = None
    telegram_file: Optional[str] = None
    telegram_size: Optional[int] = None
    telegram_command: Optional[str] = None
    telegram_error: Optional[str] = None
    dry_run: bool = False
    error: Optional[str] = None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def load_config(config_path: Optional[Path]) -> Dict[str, Any]:
    if config_path is None:
        return dict(DEFAULT_CONFIG)

    if not config_path.exists():
        raise FileNotFoundError(f"Watermark config not found: {config_path}")

    user_config = json.loads(config_path.read_text(encoding="utf-8"))

    if not isinstance(user_config, dict):
        raise ValueError("Watermark config must be a JSON object")

    return deep_merge(DEFAULT_CONFIG, user_config)


def run_command(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def ffmpeg_bin() -> str:
    for candidate in (
        os.environ.get("FFMPEG_BIN"),
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "ffmpeg",
    ):
        if candidate:
            return candidate
    return "ffmpeg"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def escape_ffmpeg_text(text: str) -> str:
    """
    Escape text for FFmpeg drawtext.
    """
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace(",", "\\,")
    )


def escape_ffmpeg_path(path: str) -> str:
    """
    Escape path for FFmpeg filter argument.
    Do not build this directly inside f-string expression with backslash.
    """
    return str(path).replace("\\", "\\\\").replace(":", "\\:")


def probe_video(video_file: Path) -> VideoMeta:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,duration",
        "-of",
        "json",
        str(video_file),
    ]

    completed = run_command(cmd, timeout=60)

    if completed.returncode != 0:
        return VideoMeta(width=0, height=0, fps=None, duration=0.0)

    try:
        raw = json.loads(completed.stdout or "{}")
        stream = (raw.get("streams") or [{}])[0]

        return VideoMeta(
            width=int(stream.get("width") or 0),
            height=int(stream.get("height") or 0),
            fps=stream.get("r_frame_rate") or None,
            duration=safe_float(stream.get("duration"), 0.0),
        )
    except Exception:
        return VideoMeta(width=0, height=0, fps=None, duration=0.0)


def resolve_path(value: Any, base_dir: Path) -> Optional[Path]:
    if not value:
        return None

    path = Path(str(value))

    if path.is_absolute():
        return path

    candidate = base_dir / path

    if candidate.exists():
        return candidate

    return path


def discover_clip_file(item: Dict[str, Any], index: int, run_dir: Path) -> Optional[Path]:
    deferred_watermarked_paths: List[Path] = []

    for key in CLIP_PATH_KEYS:
        path = resolve_path(item.get(key), run_dir)

        if path and path.exists() and path.is_file():
            if "watermarked" in path.parts:
                deferred_watermarked_paths.append(path)
                continue
            return path

    candidates = [
        run_dir / "clips" / f"clip_{index:02d}.mp4",
        run_dir / "clips" / f"short_{index:02d}.mp4",
        run_dir / "clips" / f"short_{index}.mp4",
        run_dir / "shorts" / f"short_{index:02d}.mp4",
        run_dir / "shorts" / f"short_{index}.mp4",
        run_dir / "shorts" / f"clip_{index:02d}.mp4",
        run_dir / f"clip_{index:02d}.mp4",
        run_dir / f"short_{index:02d}.mp4",
        run_dir / f"short_{index}.mp4",
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    for path in deferred_watermarked_paths:
        if path.exists() and path.is_file():
            return path

    return None


def get_crop_plan(item: Dict[str, Any]) -> Dict[str, Any]:
    crop_plan = item.get("crop_plan")
    return crop_plan if isinstance(crop_plan, dict) else {}


def get_layout_variant(crop_plan: Dict[str, Any]) -> Optional[str]:
    value = crop_plan.get("layout_variant")
    return str(value) if value else None


def get_layout(crop_plan: Dict[str, Any]) -> Optional[str]:
    value = crop_plan.get("layout")
    return str(value) if value else None


def get_subject_side(crop_plan: Dict[str, Any]) -> Optional[str]:
    focus_safety = crop_plan.get("focus_safety")

    if isinstance(focus_safety, dict):
        value = focus_safety.get("subject_side")

        if value:
            return str(value)

    subjects = crop_plan.get("subjects")

    if isinstance(subjects, list) and subjects:
        first = subjects[0]

        if isinstance(first, dict):
            pan = safe_float(first.get("pan"), 0.5)

            if pan < 0.46:
                return "left"

            if pan > 0.54:
                return "right"

            return "center"

    return None


def choose_auto_mode(crop_plan: Dict[str, Any], config: Dict[str, Any]) -> Tuple[str, str]:
    configured_mode = str(config.get("mode", "auto"))

    if configured_mode != "auto":
        return configured_mode, f"forced_mode_{configured_mode}"

    layout_variant = get_layout_variant(crop_plan) or ""
    layout = get_layout(crop_plan) or ""
    logo_path = config.get("logo_path")

    if layout_variant == "dual_active_wide_split_lr" or layout in {"split_top_bottom", "split_left_right"}:
        return "split_safe", "dual_or_split_layout_use_split_safe_watermark"

    if logo_path:
        return "logo", "logo_path_available_use_logo_mode"

    return "safe_badge", "default_safe_badge"


def choose_position(
    crop_plan: Dict[str, Any],
    mode: str,
    config: Dict[str, Any],
) -> Tuple[str, str]:
    forced_position = str(config.get("position", "auto"))

    if forced_position != "auto":
        return forced_position, f"forced_position_{forced_position}"

    layout_variant = get_layout_variant(crop_plan) or ""
    subject_side = get_subject_side(crop_plan)

    if mode == "split_safe" or layout_variant == "dual_active_wide_split_lr":
        return str(config.get("split_position", "center_top")), "split_layout_use_center_top"

    if subject_side == "left":
        return "top_right", "active_subject_left_use_top_right"

    if subject_side == "right":
        return "top_left", "active_subject_right_use_top_left"

    if layout_variant == "wide_center":
        return str(config.get("default_position", "top_right")), "wide_center_default_position"

    return str(config.get("default_position", "top_right")), "default_position"


def overlay_expr_for_position(
    position: str,
    margin_x: int,
    margin_y: int,
    video_h: int,
    center_top_ratio: float = 0.15,
) -> Tuple[str, str]:
    bottom_y = f"H-h-{max(180, int(video_h * 0.14))}"
    center_ratio_y = f"H*{clamp(center_top_ratio, 0.0, 1.0):.4f}"

    positions = {
        "top_left": (f"{margin_x}", f"{margin_y}"),
        "top_right": (f"W-w-{margin_x}", f"{margin_y}"),
        "center_top": ("(W-w)/2", f"{margin_y}"),
        "center_15_top": ("(W-w)/2", center_ratio_y),
        "center_left": (f"{margin_x}", "(H-h)/2"),
        "center_right": (f"W-w-{margin_x}", "(H-h)/2"),
        "bottom_left": (f"{margin_x}", bottom_y),
        "bottom_right": (f"W-w-{margin_x}", bottom_y),
        "center_bottom": ("(W-w)/2", bottom_y),
        "center": ("(W-w)/2", "(H-h)/2"),
    }

    return positions.get(position, positions["top_right"])


def text_expr_for_position(
    position: str,
    margin_x: int,
    margin_y: int,
    video_h: int,
    center_top_ratio: float = 0.15,
) -> Tuple[str, str]:
    bottom_y = f"main_h-text_h-{max(180, int(video_h * 0.14))}"
    center_ratio_y = f"main_h*{clamp(center_top_ratio, 0.0, 1.0):.4f}"

    positions = {
        "top_left": (f"{margin_x}", f"{margin_y}"),
        "top_right": (f"main_w-text_w-{margin_x}", f"{margin_y}"),
        "center_top": ("(main_w-text_w)/2", f"{margin_y}"),
        "center_15_top": ("(main_w-text_w)/2", center_ratio_y),
        "center_left": (f"{margin_x}", "(main_h-text_h)/2"),
        "center_right": (f"main_w-text_w-{margin_x}", "(main_h-text_h)/2"),
        "bottom_left": (f"{margin_x}", bottom_y),
        "bottom_right": (f"main_w-text_w-{margin_x}", bottom_y),
        "center_bottom": ("(main_w-text_w)/2", bottom_y),
        "center": ("(main_w-text_w)/2", "(main_h-text_h)/2"),
    }

    return positions.get(position, positions["top_right"])


def watermark_opacity_for_mode(mode: str, config: Dict[str, Any]) -> float:
    if mode == "split_safe":
        return float(config.get("split_opacity", config.get("opacity", 0.72)))

    if mode == "logo":
        return float(config.get("logo_opacity", config.get("opacity", 0.72)))

    return float(config.get("opacity", 0.72))


def opening_duration_for_item(item: Dict[str, Any]) -> float:
    duration = safe_float(item.get("opening_duration"), 0.0)
    if duration > 0:
        return duration
    opening = item.get("opening")
    if isinstance(opening, dict):
        return safe_float(opening.get("duration"), 0.0)
    return 0.0


def watermark_enable_expr(skip_seconds: float) -> str:
    skip = max(0.0, float(skip_seconds or 0.0))
    if skip <= 0:
        return ""
    return f"gte(t\\,{skip:.3f})"


def load_font(font_path: Optional[str], font_size: int):
    if not PIL_AVAILABLE:
        return None

    if font_path:
        path = Path(font_path)

        if path.exists():
            try:
                return ImageFont.truetype(str(path), font_size)
            except Exception:
                pass

    for candidate in [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, font_size)
            except Exception:
                pass

    return ImageFont.load_default()


def apply_image_opacity(image: "Image.Image", opacity: float) -> "Image.Image":
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    opacity = clamp(opacity, 0.0, 1.0)
    r, g, b, a = image.split()
    a = a.point(lambda p: int(p * opacity))
    image.putalpha(a)

    return image


def generate_badge_asset(
    asset_dir: Path,
    text: str,
    logo_path: Optional[str],
    config: Dict[str, Any],
    suffix: str,
) -> Path:
    """
    Generate transparent badge asset.
    Overall opacity is applied later by FFmpeg overlay, not here.
    """
    ensure_dir(asset_dir)

    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow is not available; cannot generate badge asset")

    font_size = int(config.get("font_size", 34))
    padding_x = int(config.get("badge_padding_x", 22))
    padding_y = int(config.get("badge_padding_y", 12))
    gap = int(config.get("badge_gap", 12))
    radius = int(config.get("badge_radius", 18))
    logo_height = int(config.get("logo_height", 110))

    font = load_font(config.get("font_path"), font_size)

    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = max(1, bbox[2] - bbox[0])
    text_h = max(1, bbox[3] - bbox[1])

    logo_img = None
    logo_w = 0

    if logo_path and Path(logo_path).exists():
        logo_img = Image.open(logo_path).convert("RGBA")
        scale = logo_height / max(1, logo_img.height)
        logo_w = max(1, int(logo_img.width * scale))
        logo_img = logo_img.resize((logo_w, logo_height), Image.LANCZOS)

    content_w = text_w + (gap + logo_w if logo_img else 0)
    content_h = max(text_h, logo_height if logo_img else 0)

    width = content_w + padding_x * 2
    height = content_h + padding_y * 2

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    if config.get("badge_shadow", True):
        shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)

        shadow_color = tuple(config.get("badge_shadow_color", [0, 0, 0, 80]))
        off_x, off_y = config.get("badge_shadow_offset", [0, 3])

        shadow_draw.rounded_rectangle(
            (max(0, off_x), max(0, off_y), width - 1, height - 1),
            radius=radius,
            fill=shadow_color,
        )

        canvas.alpha_composite(shadow)

    badge_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    badge_draw = ImageDraw.Draw(badge_layer)

    bg = tuple(config.get("badge_bg_color", [0, 0, 0, 92]))
    badge_draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=bg)
    canvas.alpha_composite(badge_layer)

    x = padding_x
    center_y = height // 2

    if logo_img:
        y = center_y - logo_img.height // 2
        canvas.alpha_composite(logo_img, (x, y))
        x += logo_w + gap

    text_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)

    text_color = tuple(config.get("font_color", [255, 255, 255, 255]))
    y = center_y - text_h // 2 - bbox[1]

    text_draw.text((x, y), text, font=font, fill=text_color)
    canvas.alpha_composite(text_layer)

    output = asset_dir / f"watermark_badge_{suffix}.png"
    canvas.save(output)

    return output


def generate_logo_asset(
    asset_dir: Path,
    logo_path: str,
    config: Dict[str, Any],
    suffix: str,
) -> Path:
    """
    Resize logo asset but keep full alpha.
    Opacity is applied only once in FFmpeg overlay filter.
    """
    ensure_dir(asset_dir)

    logo_file = Path(logo_path)

    if not logo_file.exists():
        raise FileNotFoundError(f"Logo not found: {logo_file}")

    logo_height = int(config.get("logo_height", 110))
    output = asset_dir / f"watermark_logo_{suffix}.png"

    if not PIL_AVAILABLE:
        cmd = [
            ffmpeg_bin(),
            "-y",
            "-i",
            str(logo_file),
            "-vf",
            f"scale=-1:{logo_height},format=rgba",
            "-frames:v",
            "1",
            str(output),
        ]

        completed = run_command(cmd, timeout=120)

        if completed.returncode != 0 or not output.exists():
            error = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg logo resize failed"
            raise RuntimeError(f"Pillow is not available and ffmpeg could not resize logo: {error}")

        return output

    image = Image.open(logo_file).convert("RGBA")
    scale = logo_height / max(1, image.height)
    width = max(1, int(image.width * scale))
    image = image.resize((width, logo_height), Image.LANCZOS)
    image.save(output)

    return output


def compact_source_title(text: str, max_chars: int = 38) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(8, max_chars - 3)].rstrip() + "..."


def build_source_credit_filter(
    config: Dict[str, Any],
    enable_expr: str = "",
    input_label: str = "",
    output_label: str = "",
) -> str:
    source_title = compact_source_title(str(config.get("source_title") or ""))
    if not source_title:
        return ""

    prefix = str(config.get("source_prefix") or "")
    text = source_title if source_title.lower().startswith(prefix.strip().lower()) else f"{prefix}{source_title}"
    safe_text = escape_ffmpeg_text(text)
    font_size = int(config.get("source_font_size", 34))
    alpha = clamp(float(config.get("source_opacity", 0.74)), 0.0, 1.0)
    x_expr = str(config.get("source_margin_x", 42))
    y_expr = str(config.get("source_margin_y", 72))
    font_path = config.get("font_path")
    font_part = ""
    if font_path and Path(font_path).exists():
        escaped_font_path = escape_ffmpeg_path(str(font_path))
        font_part = f":fontfile='{escaped_font_path}'"

    options = [
        f"{input_label}drawtext=text='{safe_text}'{font_part}",
        f"fontsize={font_size}",
        f"fontcolor=white@{alpha}",
        "box=1",
        "boxcolor=black@0.26",
        "boxborderw=12",
        "shadowcolor=black@0.45",
        "shadowx=2",
        "shadowy=2",
        f"x={x_expr}",
        f"y={y_expr}",
    ]
    if enable_expr:
        options.append(f"enable='{enable_expr}'")
    return ":".join(options) + output_label


def build_overlay_filter(
    opacity: float,
    x_expr: str,
    y_expr: str,
    enable_expr: str = "",
    config: Optional[Dict[str, Any]] = None,
) -> str:
    alpha = clamp(opacity, 0.0, 1.0)
    enable_part = f":enable='{enable_expr}'" if enable_expr else ""
    source_filter = build_source_credit_filter(config or {}, enable_expr=enable_expr, input_label="[base]", output_label="[v]")

    base_filter = (
        f"[1:v]format=rgba,colorchannelmixer=aa={alpha}[wm];"
        f"[0:v][wm]overlay={x_expr}:{y_expr}:format=auto{enable_part}"
    )
    if source_filter:
        return f"{base_filter}[base];{source_filter}"
    return f"{base_filter}[v]"


def build_text_filter(
    text: str,
    opacity: float,
    x_expr: str,
    y_expr: str,
    config: Dict[str, Any],
    enable_expr: str = "",
) -> str:
    font_size = int(config.get("font_size", 34))
    alpha = clamp(opacity, 0.0, 1.0)

    font_path = config.get("font_path")
    font_part = ""

    if font_path and Path(font_path).exists():
        escaped_font_path = escape_ffmpeg_path(str(font_path))
        font_part = f":fontfile='{escaped_font_path}'"

    safe_text = escape_ffmpeg_text(text)
    text_options = [
        f"drawtext=text='{safe_text}'{font_part}",
        f"fontsize={font_size}",
        f"fontcolor=white@{alpha}",
    ]

    if config.get("text_box", False):
        text_options.extend([
            "box=1",
            "boxcolor=black@0.22",
            "boxborderw=14",
        ])

    if config.get("text_shadow", True):
        shadow_x, shadow_y = config.get("text_shadow_offset", [2, 2])
        text_options.extend([
            f"shadowcolor={config.get('text_shadow_color', 'black@0.45')}",
            f"shadowx={int(shadow_x)}",
            f"shadowy={int(shadow_y)}",
        ])

    text_options.extend([
        f"x={x_expr}",
        f"y={y_expr}",
    ])
    if enable_expr:
        text_options.append(f"enable='{enable_expr}'")

    return ":".join(text_options)


def render_with_asset(
    input_file: Path,
    asset_file: Path,
    output_file: Path,
    filter_complex: str,
    config: Dict[str, Any],
    dry_run: bool,
) -> Tuple[bool, Optional[str], Optional[str]]:
    ensure_dir(output_file.parent)

    cmd = [ffmpeg_bin()]
    cmd += ["-y" if config.get("overwrite", True) else "-n"]

    cmd += [
        "-i",
        str(input_file),
        "-i",
        str(asset_file),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        str(config.get("video_codec", "libx264")),
        "-crf",
        str(config.get("crf", 18)),
        "-preset",
        str(config.get("preset", "veryfast")),
        "-pix_fmt",
        str(config.get("pix_fmt", "yuv420p")),
        "-c:a",
        str(config.get("audio_codec", "copy")),
        str(output_file),
    ]

    command_text = " ".join(shlex.quote(part) for part in cmd)

    if dry_run:
        return True, None, command_text

    completed = run_command(cmd, timeout=1200)

    if completed.returncode != 0:
        return False, completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed", command_text

    if not output_file.exists() or output_file.stat().st_size <= 0:
        return False, "ffmpeg finished but output file is missing or empty", command_text

    return True, None, command_text


def render_with_text(
    input_file: Path,
    output_file: Path,
    vf_filter: str,
    config: Dict[str, Any],
    dry_run: bool,
) -> Tuple[bool, Optional[str], Optional[str]]:
    ensure_dir(output_file.parent)

    cmd = [ffmpeg_bin()]
    cmd += ["-y" if config.get("overwrite", True) else "-n"]

    cmd += [
        "-i",
        str(input_file),
        "-vf",
        vf_filter,
        "-c:v",
        str(config.get("video_codec", "libx264")),
        "-crf",
        str(config.get("crf", 18)),
        "-preset",
        str(config.get("preset", "veryfast")),
        "-pix_fmt",
        str(config.get("pix_fmt", "yuv420p")),
        "-c:a",
        str(config.get("audio_codec", "copy")),
        str(output_file),
    ]

    command_text = " ".join(shlex.quote(part) for part in cmd)

    if dry_run:
        return True, None, command_text

    completed = run_command(cmd, timeout=1200)

    if completed.returncode != 0:
        return False, completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed", command_text

    if not output_file.exists() or output_file.stat().st_size <= 0:
        return False, "ffmpeg finished but output file is missing or empty", command_text

    return True, None, command_text


def parse_bitrate_kbps(value: Any, default: int = 128) -> int:
    if value is None:
        return default

    text = str(value).strip().lower()
    if not text:
        return default

    try:
        if text.endswith("k"):
            return max(1, int(float(text[:-1])))
        if text.endswith("m"):
            return max(1, int(float(text[:-1]) * 1000))
        return max(1, int(float(text) / 1000))
    except Exception:
        return default


def render_telegram_delivery_file(
    input_file: Path,
    output_file: Path,
    duration: float,
    config: Dict[str, Any],
    dry_run: bool,
) -> Tuple[Optional[Path], Optional[int], Optional[str], Optional[str]]:
    if not config.get("telegram_delivery_enabled", True):
        return None, None, None, None

    if duration <= 0:
        duration = safe_float(probe_video(input_file).duration, 0.0)

    if duration <= 0:
        return None, None, None, "cannot determine video duration for telegram compression"

    target_bytes = int(float(config.get("telegram_target_mb", 45)) * 1024 * 1024)
    audio_bitrate = str(config.get("telegram_audio_bitrate", "128k"))
    audio_kbps = parse_bitrate_kbps(audio_bitrate, default=128)
    min_video_kbps = int(config.get("telegram_min_video_bitrate_kbps", 800))
    max_video_kbps = int(config.get("telegram_max_video_bitrate_kbps", 3600))
    total_kbps = int((target_bytes * 8) / duration / 1000)
    video_kbps = max(min_video_kbps, min(max_video_kbps, total_kbps - audio_kbps - 80))

    ensure_dir(output_file.parent)

    if input_file.exists() and input_file.stat().st_size <= target_bytes:
        command_text = f"copy {shlex.quote(str(input_file))} {shlex.quote(str(output_file))}"
        if dry_run:
            return output_file, None, command_text, None

        shutil.copy2(input_file, output_file)
        return output_file, output_file.stat().st_size, command_text, None

    cmd = [
        ffmpeg_bin(),
        "-y" if config.get("overwrite", True) else "-n",
        "-i",
        str(input_file),
        "-c:v",
        "libx264",
        "-b:v",
        f"{video_kbps}k",
        "-maxrate",
        f"{int(video_kbps * 1.15)}k",
        "-bufsize",
        f"{int(video_kbps * 2.5)}k",
        "-preset",
        str(config.get("preset", "veryfast")),
        "-pix_fmt",
        str(config.get("pix_fmt", "yuv420p")),
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
        str(output_file),
    ]

    command_text = " ".join(shlex.quote(part) for part in cmd)

    if dry_run:
        return output_file, None, command_text, None

    completed = run_command(cmd, timeout=1200)

    if completed.returncode != 0:
        return None, None, command_text, completed.stderr.strip() or completed.stdout.strip() or "ffmpeg telegram compression failed"

    if not output_file.exists() or output_file.stat().st_size <= 0:
        return None, None, command_text, "telegram compression finished but output file is missing or empty"

    if output_file.stat().st_size > target_bytes:
        return output_file, output_file.stat().st_size, command_text, (
            f"telegram output exceeds target: {output_file.stat().st_size} > {target_bytes}"
        )

    return output_file, output_file.stat().st_size, command_text, None


def create_watermark_asset(
    mode: str,
    asset_dir: Path,
    config: Dict[str, Any],
    suffix: str,
) -> Tuple[Optional[Path], str]:
    text = str(config.get("text") or "")
    logo_path = config.get("logo_path")

    if mode == "text":
        return None, "text_draw_filter"

    if mode in {"logo", "split_safe"} and logo_path:
        return generate_logo_asset(asset_dir, str(logo_path), config, suffix), "logo_asset"

    if mode == "logo" and not logo_path:
        raise ValueError("mode=logo requires logo_path")

    if PIL_AVAILABLE:
        return generate_badge_asset(
            asset_dir=asset_dir,
            text=text,
            logo_path=str(logo_path) if logo_path else None,
            config=config,
            suffix=suffix,
        ), "badge_asset"

    if logo_path:
        return generate_logo_asset(asset_dir, str(logo_path), config, suffix), "logo_asset_no_pillow"

    return None, "text_draw_filter_no_pillow"


def make_plan(
    index: int,
    enabled: bool,
    mode: str,
    position: str,
    reason: str,
    input_file: Optional[Path],
    output_file: Optional[Path],
    crop_plan: Dict[str, Any],
    meta: Optional[VideoMeta] = None,
    overlay_x: str = "",
    overlay_y: str = "",
    opacity: float = 0.0,
    asset_file: Optional[Path] = None,
    ffmpeg_filter: Optional[str] = None,
    ffmpeg_command: Optional[str] = None,
    telegram_file: Optional[Path] = None,
    telegram_size: Optional[int] = None,
    telegram_command: Optional[str] = None,
    telegram_error: Optional[str] = None,
    dry_run: bool = False,
    error: Optional[str] = None,
) -> WatermarkPlan:
    meta = meta or VideoMeta(width=0, height=0, fps=None, duration=0.0)

    return WatermarkPlan(
        clip_index=index,
        enabled=enabled,
        mode=mode,
        position=position,
        reason=reason,
        input_file=str(input_file) if input_file else None,
        output_file=str(output_file) if output_file else None,
        asset_file=str(asset_file) if asset_file else None,
        overlay_x=overlay_x,
        overlay_y=overlay_y,
        opacity=opacity,
        layout=get_layout(crop_plan),
        layout_variant=get_layout_variant(crop_plan),
        subject_side=get_subject_side(crop_plan),
        frame_width=meta.width,
        frame_height=meta.height,
        duration=meta.duration,
        ffmpeg_filter=ffmpeg_filter,
        ffmpeg_command=ffmpeg_command,
        telegram_file=str(telegram_file) if telegram_file else None,
        telegram_size=telegram_size,
        telegram_command=telegram_command,
        telegram_error=telegram_error,
        dry_run=dry_run,
        error=error,
    )


def process_highlight(
    index: int,
    item: Dict[str, Any],
    run_dir: Path,
    config: Dict[str, Any],
    dry_run: bool,
) -> WatermarkPlan:
    crop_plan = get_crop_plan(item)
    input_file = discover_clip_file(item, index, run_dir)

    if not config.get("enabled", True):
        return make_plan(
            index=index,
            enabled=False,
            mode="disabled",
            position="none",
            reason="watermark_disabled",
            input_file=input_file,
            output_file=input_file,
            crop_plan=crop_plan,
            dry_run=dry_run,
        )

    if input_file is None:
        return make_plan(
            index=index,
            enabled=True,
            mode="error",
            position="unknown",
            reason="clip_file_not_found",
            input_file=None,
            output_file=None,
            crop_plan=crop_plan,
            dry_run=dry_run,
            error="Clip file not found for highlight",
        )

    meta = probe_video(input_file)
    mode, mode_reason = choose_auto_mode(crop_plan, config)
    position, position_reason = choose_position(crop_plan, mode, config)
    opacity = watermark_opacity_for_mode(mode, config)
    opening_duration = opening_duration_for_item(item)
    enable_expr = watermark_enable_expr(opening_duration)

    margin_x = int(config.get("safe_margin_x", 48))
    margin_y = int(config.get("safe_margin_y", 72))

    x_expr, y_expr = overlay_expr_for_position(
        position=position,
        margin_x=margin_x,
        margin_y=margin_y,
        video_h=meta.height,
        center_top_ratio=float(config.get("center_top_ratio", 0.15)),
    )

    asset_dir = run_dir / "watermark_assets"
    output_dir = run_dir / "watermarked"
    ensure_dir(output_dir)

    output_file = output_dir / f"{input_file.stem}_wm.mp4"
    suffix = f"{index:02d}_{mode}_{position}"

    base_reason = f"{mode_reason};{position_reason}"
    if opening_duration > 0:
        base_reason = f"{base_reason};skip_opening_{opening_duration:.3f}s"

    try:
        asset_file, asset_reason = create_watermark_asset(
            mode=mode,
            asset_dir=asset_dir,
            config=config,
            suffix=suffix,
        )

        reason = f"{base_reason};{asset_reason}"

        if asset_file:
            filter_complex = build_overlay_filter(
                opacity=opacity,
                x_expr=x_expr,
                y_expr=y_expr,
                enable_expr=enable_expr,
                config=config,
            )

            ok, error, command_text = render_with_asset(
                input_file=input_file,
                asset_file=asset_file,
                output_file=output_file,
                filter_complex=filter_complex,
                config=config,
                dry_run=dry_run,
            )

            if not ok:
                return make_plan(
                    index=index,
                    enabled=True,
                    mode=mode,
                    position=position,
                    reason=reason,
                    input_file=input_file,
                    output_file=None,
                    crop_plan=crop_plan,
                    meta=meta,
                    overlay_x=x_expr,
                    overlay_y=y_expr,
                    opacity=opacity,
                    asset_file=asset_file,
                    ffmpeg_filter=filter_complex,
                    ffmpeg_command=command_text,
                    dry_run=dry_run,
                    error=error,
                )

            telegram_file, telegram_size, telegram_command, telegram_error = render_telegram_delivery_file(
                input_file=output_file,
                output_file=output_file.with_name(f"{output_file.stem}_telegram.mp4"),
                duration=meta.duration,
                config=config,
                dry_run=dry_run,
            )

            return make_plan(
                index=index,
                enabled=True,
                mode=mode,
                position=position,
                reason=reason,
                input_file=input_file,
                output_file=output_file if not dry_run else None,
                crop_plan=crop_plan,
                meta=meta,
                overlay_x=x_expr,
                overlay_y=y_expr,
                opacity=opacity,
                asset_file=asset_file,
                ffmpeg_filter=filter_complex,
                ffmpeg_command=command_text,
                telegram_file=telegram_file,
                telegram_size=telegram_size,
                telegram_command=telegram_command,
                telegram_error=telegram_error,
                dry_run=dry_run,
                error=None,
            )

        text_x_expr, text_y_expr = text_expr_for_position(
            position=position,
            margin_x=margin_x,
            margin_y=margin_y,
            video_h=meta.height,
            center_top_ratio=float(config.get("center_top_ratio", 0.15)),
        )

        vf = build_text_filter(
            text=str(config.get("text") or "KILASAN VIDEO"),
            opacity=opacity,
            x_expr=text_x_expr,
            y_expr=text_y_expr,
            config=config,
            enable_expr=enable_expr,
        )
        source_vf = build_source_credit_filter(config, enable_expr=enable_expr)
        if source_vf:
            vf = f"{vf},{source_vf}"

        ok, error, command_text = render_with_text(
            input_file=input_file,
            output_file=output_file,
            vf_filter=vf,
            config=config,
            dry_run=dry_run,
        )

        if not ok:
            return make_plan(
                index=index,
                enabled=True,
                mode=mode,
                position=position,
                reason=reason,
                input_file=input_file,
                    output_file=None,
                    crop_plan=crop_plan,
                    meta=meta,
                    overlay_x=text_x_expr,
                    overlay_y=text_y_expr,
                    opacity=opacity,
                    asset_file=None,
                ffmpeg_filter=vf,
                ffmpeg_command=command_text,
                dry_run=dry_run,
                error=error,
            )

        telegram_file, telegram_size, telegram_command, telegram_error = render_telegram_delivery_file(
            input_file=output_file,
            output_file=output_file.with_name(f"{output_file.stem}_telegram.mp4"),
            duration=meta.duration,
            config=config,
            dry_run=dry_run,
        )

        return make_plan(
            index=index,
            enabled=True,
            mode=mode,
            position=position,
            reason=reason,
            input_file=input_file,
            output_file=output_file if not dry_run else None,
            crop_plan=crop_plan,
            meta=meta,
            overlay_x=text_x_expr,
            overlay_y=text_y_expr,
            opacity=opacity,
            asset_file=None,
            ffmpeg_filter=vf,
            ffmpeg_command=command_text,
            telegram_file=telegram_file,
            telegram_size=telegram_size,
            telegram_command=telegram_command,
            telegram_error=telegram_error,
            dry_run=dry_run,
            error=None,
        )

    except Exception as exc:
        return make_plan(
            index=index,
            enabled=True,
            mode=mode,
            position=position,
            reason=base_reason,
            input_file=input_file,
            output_file=None,
            crop_plan=crop_plan,
            meta=meta,
            overlay_x=x_expr,
            overlay_y=y_expr,
            opacity=opacity,
            dry_run=dry_run,
            error=str(exc),
        )


def process_result_json(
    result_path: Path,
    run_dir: Path,
    config: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
    data = json.loads(result_path.read_text(encoding="utf-8"))
    highlights = data.get("highlights", [])

    if not isinstance(highlights, list):
        raise ValueError("Invalid result.json: highlights must be a list")

    plans: List[Dict[str, Any]] = []

    for index, item in enumerate(highlights, start=1):
        if not isinstance(item, dict):
            continue

        plan = process_highlight(
            index=index,
            item=item,
            run_dir=run_dir,
            config=config,
            dry_run=dry_run,
        )

        plan_dict = asdict(plan)
        item["watermark_plan"] = plan_dict

        if plan.output_file and not plan.error and not dry_run:
            item["watermarked_file"] = plan.output_file
            item["final_video_file"] = plan.output_file
            if plan.telegram_file:
                item["telegram_video_file"] = plan.telegram_file
                item["telegram_video_size"] = plan.telegram_size
                item["telegram_delivery_profile"] = "telegram"
                item.pop("telegram_delivery_error", None)
            if plan.telegram_error:
                item["telegram_delivery_error"] = plan.telegram_error
            item.pop("watermark_error", None)
        elif plan.error:
            item["watermark_error"] = plan.error
            item.pop("watermarked_file", None)
        elif dry_run:
            item["watermark_dry_run"] = True

        plans.append(plan_dict)

    watermark_plan_path = run_dir / "watermark_plan.json"
    watermark_plan_path.write_text(
        json.dumps(
            {
                "mode": "professional_adaptive_watermark",
                "dry_run": dry_run,
                "clips": plans,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    success_count = sum(1 for plan in plans if not plan.get("error") and (dry_run or plan.get("output_file")))
    error_count = sum(1 for plan in plans if plan.get("error"))

    data["watermark_summary"] = {
        "engine": "professional_watermark_generator_v2",
        "dry_run": dry_run,
        "processed_count": len(plans),
        "success_count": success_count,
        "error_count": error_count,
        "telegram_count": sum(1 for plan in plans if plan.get("telegram_file")),
        "watermark_plan_file": str(watermark_plan_path),
    }

    result_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return data["watermark_summary"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Professional adaptive watermark generator for clipper engine"
    )

    parser.add_argument("result_json", help="Path to result.json")
    parser.add_argument("run_dir", help="Run directory containing clips and crop_plan outputs")
    parser.add_argument("--config", default=None, help="Optional watermark_config.json")
    parser.add_argument("--text", default=None, help="Override watermark text")
    parser.add_argument("--font", default=None, help="Override font path")
    parser.add_argument("--logo", default=None, help="Override logo path")
    parser.add_argument("--source-title", default=None, help="Source credit shown on the main video, not thumbnail")
    parser.add_argument(
        "--mode",
        default=None,
        choices=["auto", "safe_badge", "split_safe", "logo", "text"],
        help="Override watermark mode",
    )
    parser.add_argument(
        "--position",
        default=None,
        help="Override position: auto, top_right, top_left, center_top, center_15_top, center_right, center_left, center_bottom, bottom_right, bottom_left, center",
    )
    parser.add_argument("--opacity", type=float, default=None, help="Override opacity")
    parser.add_argument("--logo-height", type=int, default=None, help="Override logo height")
    parser.add_argument("--dry-run", action="store_true", help="Build plans and FFmpeg commands without rendering")

    return parser.parse_args()


def main() -> None:
    # Setup logging at the start
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stdout
    )
    
    args = parse_args()

    logger.info("Starting watermark generation...")
    logger.info(f"  result_json: {args.result_json}")
    logger.info(f"  run_dir: {args.run_dir}")
    if args.config:
        logger.info(f"  config: {args.config}")
    if args.text:
        logger.info(f"  text: {args.text}")
    if args.mode:
        logger.info(f"  mode: {args.mode}")
    if args.position:
        logger.info(f"  position: {args.position}")
    logger.info(f"  dry_run: {args.dry_run}")

    result_path = Path(args.result_json)
    run_dir = Path(args.run_dir)

    if not result_path.exists():
        logger.error(f"result.json not found: {result_path}")
        raise SystemExit(f"result.json not found: {result_path}")

    ensure_dir(run_dir)

    config = load_config(Path(args.config) if args.config else None)

    if args.text is not None:
        config["text"] = args.text

    if args.font is not None:
        config["font_path"] = args.font

    if args.logo is not None:
        config["logo_path"] = args.logo

    if args.source_title is not None:
        config["source_title"] = args.source_title

    if args.mode is not None:
        config["mode"] = args.mode

    if args.position is not None:
        config["position"] = args.position

    if args.opacity is not None:
        config["opacity"] = args.opacity
        config["logo_opacity"] = args.opacity
        config["split_opacity"] = args.opacity

    if args.logo_height is not None:
        config["logo_height"] = args.logo_height

    logger.info("Processing result.json for watermark...")
    summary = process_result_json(
        result_path=result_path,
        run_dir=run_dir,
        config=config,
        dry_run=bool(args.dry_run),
    )
    
    # Log summary
    logger.info(f"Watermark processing complete")
    logger.info(f"  processed: {summary.get('processed_count', 0)}")
    logger.info(f"  success: {summary.get('success_count', 0)}")
    logger.info(f"  errors: {summary.get('error_count', 0)}")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
