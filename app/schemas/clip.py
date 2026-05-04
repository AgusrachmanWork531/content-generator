from pydantic import BaseModel
from typing import Optional, List, Any, Dict, Union

class Segment(BaseModel):
    start: str
    end: str
    desc: Optional[str] = None

class ClipDownloadRequest(BaseModel):
    url: str
    start_time: Optional[Union[float, str]] = None
    end_time: Optional[Union[float, str]] = None
    auto_reframe: bool = False
    add_subtitles: bool = False
    auto_merge: bool = False                      # New: for multi-segment stitching
    segments: Optional[List[Segment]] = None     # New: list of segments to merge
    ranking: Optional[int] = None                 # New: ranking priority
    platform: Optional[str] = None
    enable_youtube_upload: Optional[bool] = None
    metaData: Optional[Dict[str, Any]] = None     # Should include 'title', 'description', etc.
    narration_text: Optional[str] = None          # Opening narration text for Edge-TTS
    transcript_languages: Optional[List[str]] = ['id', 'en']
    row_index: Optional[int] = None               # Original row index from Google Sheets
    anti_bot_vfx: bool = True                    # If True, adds subtle zoom/color shifts
    satisfying: bool = False                      # If True, adds B-roll split screen

class ClipItemResponse(BaseModel):
    status: str
    message: str
    file_id: Optional[str] = None
    download_url: Optional[str] = None
    transcript_url: Optional[str] = None
    subtitle_json_url: Optional[str] = None
    subtitle_srt_url: Optional[str] = None
    upload_url: Optional[str] = None
    platform: Optional[str] = None

class ClipDownloadResponse(BaseModel):
    status: str
    results: List[ClipItemResponse]
