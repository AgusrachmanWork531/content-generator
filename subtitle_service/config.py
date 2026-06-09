"""
Subtitle Service Configuration.

Based on ISSUE_NEW_PIPLINE_SUBTITLE.md requirements.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


# Subtitle style presets with all parameters
SUBTITLE_STYLES: Dict[str, dict] = {
    "shorts_pro": {
        "words_per_cap": 2,
        "max_chars_per_caption": 18,
        "font": "Montserrat ExtraBold",
        "fontsize": 82,
        "outline": 9,
        "shadow": 1,
        "margin_v": 480,
        "margin_lr": 120,
        "active": "#FFCC00",
        "inactive": "#E0E0E0",
        "outline_color": "#000000",
        "tail_hold": 0.12,
        "pop_in_ms": 50,
        "pop_out_ms": 120,
        "pop_outline_extra": 4,
        "pop_blur": 0.5,
        "fsp": 2,
        "use_scale_animation": False,
        "per_word_popup": True,
    },
    "viral_clip_pro": {
        "words_per_cap": 2,
        "max_chars_per_caption": 16,
        "font": "Montserrat ExtraBold",
        "fontsize": 82,
        "outline": 9,
        "shadow": 1,
        "margin_v": 480,
        "margin_lr": 120,
        "active": "#FFCC00",
        "inactive": "#E0E0E0",
        "outline_color": "#000000",
        "tail_hold": 0.12,
        "pop_in_ms": 50,
        "pop_out_ms": 120,
        "pop_outline_extra": 4,
        "pop_blur": 0.5,
        "fsp": 2,
        "use_scale_animation": False,
        "per_word_popup": True,
    },
    "shorts_pro_pop": {
        "words_per_cap": 2,
        "max_chars_per_caption": 16,
        "font": "Montserrat ExtraBold",
        "fontsize": 82,
        "outline": 9,
        "shadow": 1,
        "margin_v": 480,
        "margin_lr": 120,
        "active": "#FFCC00",
        "inactive": "#E0E0E0",
        "outline_color": "#000000",
        "tail_hold": 0.12,
        "pop_in_ms": 90,
        "pop_out_ms": 180,
        "pop_outline_extra": 4,
        "pop_blur": 0.8,
        "fsp": 2,
        "use_scale_animation": True,
        "per_word_popup": True,
    },
    "cinema_bold": {
        # Preset premium – CapCut / Submagic style.
        # Per-word popup: setiap kata yang diucapkan mendapat Dialogue sendiri.
        "words_per_cap": 2,
        "max_chars_per_caption": 16,
        "font": "Montserrat Black",
        "fontsize": 82,
        "outline": 9,
        "shadow": 1,
        "margin_v": 480,
        "margin_lr": 120,
        "active": "#FFCC00",       # Kuning cerah, kontras tinggi
        "inactive": "#E0E0E0",     # Abu muda agar terlihat tapi tidak dominan
        "outline_color": "#000000",
        "tail_hold": 0.12,
        "pop_in_ms": 50,           # Sangat cepat – snappy & presisi
        "pop_out_ms": 120,
        "pop_outline_extra": 4,    # Glow effect dramatis saat kata aktif
        "pop_blur": 0.5,
        "fsp": 3,                  # Letter spacing premium
        "use_scale_animation": False,
        "per_word_popup": True,    # Tiap kata diucapkan = popup sendiri
    },
    "default": {
        "words_per_cap": 3,
        "max_chars_per_caption": 28,
        "font": "Montserrat",
        "fontsize": 72,
        "outline": 7,
        "shadow": 0,
        "margin_v": 120,
        "margin_lr": 70,
        "active": "#FFB117",
        "inactive": "#FFFFFF",
        "outline_color": "#000000",
        "tail_hold": 0.0,
        "pop_in_ms": 90,
        "pop_out_ms": 200,
        "pop_outline_extra": 3,
        "pop_blur": 0.8,
        "fsp": 0,
        "use_scale_animation": False,
        "per_word_popup": False,
    },
}


def get_subtitle_style(style_name: str = "cinema_bold") -> dict:
    """Get subtitle style configuration by name."""
    return SUBTITLE_STYLES.get(style_name, SUBTITLE_STYLES["cinema_bold"])


def validate_caption_length(caption_text: str, style_name: str = "cinema_bold") -> tuple[bool, str]:
    """
    Validate caption text length against style's max_chars_per_caption.
    
    Args:
        caption_text: The caption text to validate
        style_name: The style preset name
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    style_config = get_subtitle_style(style_name)
    max_chars = style_config.get("max_chars_per_caption", 28)
    
    # Strip ASS tags for length calculation
    import re
    clean_text = re.sub(r'\{[^}]*\}', '', caption_text)
    clean_text = clean_text.strip()
    
    actual_length = len(clean_text)
    
    if actual_length > max_chars:
        return (False, f"Caption exceeds max_chars_per_caption ({max_chars}): got {actual_length}")
    
    return (True, "")


class Settings(BaseSettings):
    """Subtitle service settings from environment variables."""

    # Enable/disable subtitle API
    enable_subtitle_api: bool = Field(
        default=False,
        description="Enable the subtitle API service"
    )

    # Engine configuration
    subtitle_engine: str = Field(
        default="auto-captions",
        description="Primary subtitle engine (auto-captions, whisperx)"
    )
    subtitle_fallback_engine: str = Field(
        default="whisperx",
        description="Fallback subtitle engine"
    )

    # Output directories
    subtitle_output_dir: Path = Field(
        default=Path("storage/subtitle-jobs"),
        description="Base output directory for subtitle jobs"
    )

    # Burn configuration
    subtitle_burn_default: bool = Field(
        default=False,
        description="Default burn subtitle to video"
    )

    # Timing configuration
    subtitle_require_word_timestamps: bool = Field(
        default=False,
        description="Require word-level timestamps"
    )
    subtitle_allow_emergency_approx_timing: bool = Field(
        default=True,
        description="Allow emergency approximate timing fallback"
    )

    # Caption constraints
    subtitle_max_words_per_caption: int = Field(
        default=4,
        description="Maximum words per caption line"
    )
    subtitle_max_chars_per_caption: int = Field(
        default=28,
        description="Maximum characters per caption line"
    )

    # FFmpeg configuration
    ffmpeg_bin: str = Field(
        default="/usr/bin/ffmpeg",
        description="Path to FFmpeg binary"
    )

    # API configuration
    subtitle_api_host: str = Field(
        default="0.0.0.0",
        description="API host"
    )
    subtitle_api_port: int = Field(
        default=8088,
        description="API port"
    )
    subtitle_api_token: str = Field(
        default="change-me",
        description="API authentication token"
    )

    class Config:
        env_prefix = "SUBTITLE_"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def ensure_subtitle_output_dir() -> Path:
    """Ensure subtitle output directory exists."""
    settings = get_settings()
    output_dir = settings.subtitle_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir
