import os
import whisper
import ffmpeg
import asyncio
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

class TranscriberService:
    def __init__(self):
        self._model = None

    @property
    def model(self):
        if self._model is None:
            # Reverting to CPU: Whisper Dynamic Time Warping (word timestamps) crashes on MPS
            # due to missing float64 tensor support natively in Apple Metal.
            device = "cpu"
            logger.info(f"Loading Whisper model '{settings.WHISPER_MODEL}' on device: {device}...")
            self._model = whisper.load_model(settings.WHISPER_MODEL, device=device)
        return self._model

    async def transcribe(self, video_path: str) -> list:
        """
        Extracts audio from video and transcribes it with word-level timestamps.
        """
        audio_path = video_path.replace('.mp4', '.wav')
        
        # Step 1: Extract audio using ffmpeg (16k mono for Whisper)
        if not os.path.exists(audio_path):
            logger.info(f"Extracting audio to {audio_path}...")
            try:
                stream = ffmpeg.input(video_path)
                stream = ffmpeg.output(stream, audio_path, ac=1, ar='16k')
                await asyncio.to_thread(ffmpeg.run, stream, overwrite_output=True, quiet=True)
            except Exception as e:
                logger.error(f"Failed to extract audio: {e}")
                raise e
        
        # Step 2: Transcribe using Whisper with language hint and anti-hallucination config
        logger.info(f"Transcribing with Whisper '{settings.WHISPER_MODEL}' (lang={settings.WHISPER_LANGUAGE})...")
        result = await asyncio.to_thread(
            self.model.transcribe, 
            audio_path,
            language=settings.WHISPER_LANGUAGE,
            verbose=False, 
            word_timestamps=True,
            no_speech_threshold=0.4,     # Suppress non-speech frames
            logprob_threshold=-1.0,      # Reject low-confidence segments
            condition_on_previous_text=False,  # Prevent hallucination chaining
        )
        
        # Cleanup audio
        if os.path.exists(audio_path):
            os.remove(audio_path)
            
        return result['segments']

transcriber_service = TranscriberService()
