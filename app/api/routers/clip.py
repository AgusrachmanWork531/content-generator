from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
import os
import uuid
import logging
import time
import json
import asyncio
from typing import Optional, Union, List, Dict
from app.schemas.clip import ClipDownloadRequest, ClipDownloadResponse, ClipItemResponse
from app.services.youtube import download_youtube_clip, crop_video, _parse_time_to_seconds
from app.services.clipper_engine import ClipperEngine
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

from app.services.transcriber import transcriber_service
from app.services.subtitle import subtitle_service
from app.services.youtube import download_youtube_clip, crop_video, _parse_time_to_seconds, extract_video_id
from app.services.youtube_upload import upload_short
import re

from app.services.clip_processor import process_clip_request
from app.services.compilation_processor import compilation_processor
from app.services.google_sheets import google_sheets_service
from app.core.tasks import _process_pending_sheets_rows

@router.post("/sync-sheets")
async def sync_sheets(background_tasks: BackgroundTasks):
    """
    Manually trigger a sync with Google Sheets to process pending rows.
    Runs in the background to avoid timing out.
    """
    background_tasks.add_task(_process_pending_sheets_rows)
    return {"status": "success", "message": "Google Sheets sync started in the background"}

@router.post("/compilation/sync")
async def sync_compilation():
    """
    Manually trigger a sync with Google Sheets to process pending compilations.
    Processes compilations in parallel.
    """
    compilations = google_sheets_service.get_compilation_pending_rows()
    
    if not compilations:
        return {"status": "success", "message": "No pending compilations found"}

    results = []
    
    async def process_single_comp(comp_id, clips):
        try:
            logger.info(f"Starting compilation for ID: {comp_id}")
            output_filename = await compilation_processor.process_compilation(comp_id, clips)
            
            # Mark as done in Sheets
            row_indices = [c['row_index'] for c in clips]
            result_url = f"/download/{output_filename}"
            google_sheets_service.mark_compilation_as_done(row_indices, result_url)
            
            return {"compilation_id": comp_id, "status": "success", "download_url": result_url}
        except Exception as e:
            logger.error(f"Failed to process compilation {comp_id}: {e}")
            return {"compilation_id": comp_id, "status": "error", "message": str(e)}

    # Process all pending compilations in parallel
    comp_tasks = [process_single_comp(cid, clips) for cid, clips in compilations.items()]
    results = await asyncio.gather(*comp_tasks)

    return {"status": "success", "results": results}

@router.post("/download-clip", response_model=ClipDownloadResponse)
async def download_clip(requests: List[ClipDownloadRequest], background_tasks: BackgroundTasks):
    results = []
    # We process them sequentially in the loop for this endpoint
    for request in requests:
        try:
            result = await process_clip_request(request)
            results.append(result)
        except Exception as e:
            logger.error(f"Error processing {request.url}: {e}")
            results.append(ClipItemResponse(
                status="error",
                message=str(e),
                platform=request.platform
            ))

    return ClipDownloadResponse(
        status="success",
        results=results
    )



@router.get("/download/{filename}")
async def get_file(filename: str):
    file_path = os.path.join(settings.TMP_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found or expired")
    
    # Detect media type from extension
    if filename.endswith(".srt"):
        media_type = "text/plain; charset=utf-8"
    elif filename.endswith(".jpg") or filename.endswith(".jpeg"):
        media_type = "image/jpeg"
    elif filename.endswith(".json"):
        media_type = "application/json"
    else:
        media_type = "video/mp4"
    
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename
    )

