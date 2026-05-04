from pydantic import BaseModel
from typing import List, Dict, Optional

class TranscriptRequest(BaseModel):
    url: str
    languages: Optional[List[str]] = ['en', 'id']

class TranscriptSegment(BaseModel):
    text: str
    start: float
    duration: float

class TranscriptResponse(BaseModel):
    status: str
    video_id: str
    transcript: List[Dict]
