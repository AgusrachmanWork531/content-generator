import os
from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices
from pathlib import Path

class Settings(BaseSettings):
    PROJECT_NAME: str = "YouTube Clip Downloader"
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    TMP_DIR: Path = Path("./tmp_downloads")
    FULL_VIDEO_DIR: Path = Path("./tmp_downloads/full_video")
    FILE_TTL_SECONDS: int = 3600  # 1 hour
    CLEANUP_INTERVAL_SECONDS: int = 300  # 5 minutes
    SHEETS_SYNC_INTERVAL_SECONDS: int = 60  # 1 minute
    ENABLE_YOUTUBE_UPLOAD: bool = Field(False, validation_alias=AliasChoices('YT_CLIP_ENABLE_YOUTUBE_UPLOAD', 'YOUTUBE'))
    WHISPER_MODEL: str = "small"  # Options: tiny, base, small, medium, large
    WHISPER_LANGUAGE: str = "id"  # BCP-47 language code, 'id' = Bahasa Indonesia
    PREFERRED_RESOLUTION: int = 1080
    PROXIMITY_BASE: float = 0.35        # Default base proximity threshold (0.10-0.50)
    PROXIMITY_MODE: str = "auto"         # "auto" = dynamic AI, "manual" = static base value
    RUN_MODE: str = "both"              # Options: clipper, compilation, both
    
    # BGM Settings
    ENABLE_BGM: bool = True
    BGM_VOLUME: float = 0.30            # Balanced level for background presence
    BGM_DUCKING_THRESHOLD: float = 0.25  # Optimal sensitivity for varied voice levels
    BGM_DUCKING_RATIO: float = 3.0      # Professional drop ratio (3:1)
    BGM_DUCKING_ATTACK: int = 30        # Quick but smooth transition in
    BGM_DUCKING_RELEASE: int = 800      # Natural recovery after talent stops speaking

    # Opening Narrator (Edge-TTS) Settings
    VOICEOVER_VOICE: str = "id-ID-GadisNeural"  # Best Bahasa Indonesia neural voice
    VOICEOVER_RATE: str = "+10%"                 # Slightly faster, natural pacing
    VOICEOVER_PITCH: str = "+0Hz"               # Neutral pitch, clear intonation

    # Originality Settings
    SATISFYING_DIR: Path = Path("./assets/satisfying_content")
    ENABLE_ANTI_BOT_VFX: bool = True

    class Config:
        env_prefix = "YT_CLIP_"

settings = Settings()

# Ensure tmp directory exists
os.makedirs(settings.TMP_DIR, exist_ok=True)
