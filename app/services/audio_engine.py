import os
import logging
import ffmpeg
from app.core.config import settings

logger = logging.getLogger(__name__)

class AudioEngine:
    def apply_bgm_with_ducking(self, video_stream, audio_stream):
        """
        Applies background music with automatic ducking when speech is detected.
        """
        bgm_dir = settings.BASE_DIR / "assets" / "bgm"
        bgm_files = list(bgm_dir.glob("*.mp3")) + list(bgm_dir.glob("*.wav"))
        
        if not bgm_files:
            logger.warning("No BGM files found in assets/bgm. Skipping BGM.")
            return video_stream, audio_stream
            
        bgm_path = str(bgm_files[0]) # Use the first one for now
        logger.info(f"Applying BGM: {bgm_path}")
        
        # Use stream_loop=-1 for infinite looping of audio file
        bgm_stream = ffmpeg.input(bgm_path, stream_loop=-1)
        
        # Simple mix with volume reduction on BGM
        bgm_stream = bgm_stream.filter('volume', 0.15)
        audio_stream = ffmpeg.filter([audio_stream, bgm_stream], 'amix', inputs=2, duration='shortest')
        
        return video_stream, audio_stream

audio_engine = AudioEngine()
