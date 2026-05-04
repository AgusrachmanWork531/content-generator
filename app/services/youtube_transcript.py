import logging
from typing import List, Optional, Dict
from youtube_transcript_api import YouTubeTranscriptApi
from app.services.youtube import extract_video_id

logger = logging.getLogger(__name__)

class YouTubeTranscriptService:
    def get_transcript(self, url: str, languages: List[str] = ['id', 'en']) -> Optional[List[Dict]]:
        """
        Fetches transcript from YouTube for the given video URL.
        """
        video_id = extract_video_id(url)
        try:
            # Instantiate the API class first as required by this version
            api = YouTubeTranscriptApi()
            try:
                transcript_list = api.list(video_id)
                transcript = transcript_list.find_transcript(languages)
                result = transcript.fetch()
                # Type-Guard: Convert to list of dicts regardless of library version
                if not isinstance(result, list):
                    result = [result]
                
                final_list = []
                for item in result:
                    # Safely convert to dict or extract needed fields
                    if isinstance(item, dict):
                        final_list.append(item)
                    else:
                        # Extract attributes if it's an object (FetchedTranscriptSnippet)
                        final_list.append({
                            'text': getattr(item, 'text', str(item)),
                            'start': getattr(item, 'start', 0.0),
                            'duration': getattr(item, 'duration', 0.0)
                        })
                return final_list
            except:
                # Fallback to direct module function if instance methods fail
                import youtube_transcript_api
                if hasattr(youtube_transcript_api, 'get_transcript'):
                    return youtube_transcript_api.get_transcript(video_id, languages=languages)
                raise
        except Exception as e:
            logger.warning(f"All transcript fetch attempts failed for {video_id}: {e}")
            return None

youtube_transcript_service = YouTubeTranscriptService()
