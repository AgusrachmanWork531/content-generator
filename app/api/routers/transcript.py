from fastapi import APIRouter, HTTPException
import logging
from app.schemas.transcript import TranscriptRequest, TranscriptResponse
from app.services.youtube import download_youtube_clip, extract_video_id
from app.services.transcriber import transcriber_service
import os
import asyncio
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/get-transcript", response_model=TranscriptResponse)
async def get_transcript(request: TranscriptRequest):
    try:
        video_id = extract_video_id(request.url)
        logger.info(f"Generating transcript via Whisper for: {video_id}")
        
        # Download (reuse logic from clip pipeline)
        filename = await asyncio.to_thread(download_youtube_clip, request.url)
        video_path = os.path.join(settings.TMP_DIR, filename)
        
        try:
            # Transcribe
            segments = await transcriber_service.transcribe(video_path)
            
            # Map to legacy TranscriptResponse format (simplified)
            formatted_transcript = [
                {'text': seg.get('text', ''), 'start': seg.get('start', 0), 'duration': seg.get('end', 0) - seg.get('start', 0)}
                for seg in segments
            ]
            
            return TranscriptResponse(
                status="success",
                video_id=video_id,
                transcript=formatted_transcript
            )
        finally:
            # Cleanup source video
            if os.path.exists(video_path):
                os.remove(video_path)
                
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error fetching transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))
