import os
import time
import threading
import logging
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import shutil

# Directories to NEVER delete during TTL cleanup
PROTECTED_DIRS = {"full_video", "thumbnail_video"}

def cleanup_expired_files():
    """
    Scans the tmp directory and removes files/dirs older than the TTL.
    Skips protected directories (full_video, thumbnail_video).
    """
    while True:
        try:
            logger.info("Running cleanup task...")
            now = time.time()
            removed = 0
            for entry in os.listdir(settings.TMP_DIR):
                entry_path = os.path.join(settings.TMP_DIR, entry)

                # Skip protected directories
                if os.path.isdir(entry_path):
                    if entry in PROTECTED_DIRS:
                        continue
                    # Check age of directory
                    dir_age = now - os.path.getctime(entry_path)
                    if dir_age > settings.FILE_TTL_SECONDS:
                        shutil.rmtree(entry_path, ignore_errors=True)
                        removed += 1
                        logger.info(f"Deleted expired dir: {entry}")
                    continue

                if os.path.isfile(entry_path):
                    file_age = now - os.path.getctime(entry_path)
                    if file_age > settings.FILE_TTL_SECONDS:
                        os.remove(entry_path)
                        removed += 1
                        logger.info(f"Deleted expired file: {entry}")

            if removed:
                logger.info(f"[Cleanup TTL] Removed {removed} expired items.")
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")
        
        time.sleep(settings.CLEANUP_INTERVAL_SECONDS)

import asyncio
from app.services.google_sheets import google_sheets_service
from app.services.clip_processor import process_clip_request
from app.schemas.clip import ClipDownloadRequest

async def _process_pending_sheets_rows():
    """
    Fetches pending rows from Google Sheets and processes them.
    """
    logger.info("Checking Google Sheets for pending tasks...")
    pending_rows = google_sheets_service.get_pending_rows()
    
    if not pending_rows:
        logger.info("No pending tasks in Google Sheets.")
        return

    for row in pending_rows:
        try:
            logger.info(f"Processing row {row['row_index']} from Google Sheets: {row['url']}")
            
            # Map row data to ClipDownloadRequest
            request = ClipDownloadRequest(
                url=row['url'],
                start_time=row['start_time'],
                end_time=row['end_time'],
                auto_reframe=row['reframe'],
                add_subtitles=row['subtitles'],
                platform=row['platform'],
                enable_youtube_upload=row['upload'],
                metaData={
                    "title": row.get('title', ''),
                    "description": row.get('description', ''),
                    "tags": row.get('tags', ''),
                    "thumbnail_image": row.get('thumbnail_image', '')
                },
                narration_text=row.get('narration_text'),
                row_index=row['row_index'],
                anti_bot_vfx=row.get('anti_bot', True),
                satisfying=row.get('satisfying', False)
            )
            
            # Process the clip
            result = await process_clip_request(request)
            
            if result.status == "success":
                # Mark as done in Sheets
                google_sheets_service.mark_as_done(row['row_index'])
                logger.info(f"Successfully processed and marked row {row['row_index']} as DONE.")
            else:
                logger.error(f"Failed to process row {row['row_index']}: {result.message}")
                
        except Exception as e:
            logger.error(f"Error processing Sheets row {row.get('row_index')}: {e}")

async def run_sheets_sync_periodically():
    while True:
        try:
            await _process_pending_sheets_rows()
        except Exception as e:
            logger.error(f"Error in sheets sync loop: {e}")
        
        await asyncio.sleep(settings.SHEETS_SYNC_INTERVAL_SECONDS)

async def _process_pending_compilations():
    """
    Fetches pending compilations from Google Sheets and processes them.
    """
    logger.info("Checking Google Sheets for pending compilations...")
    compilations = google_sheets_service.get_compilation_pending_rows()
    
    if not compilations:
        logger.info("No pending compilations.")
        return

    from app.services.compilation_processor import compilation_processor
    
    for comp_id, clips in compilations.items():
        try:
            logger.info(f"Starting compilation for ID: {comp_id}")
            
            # clips is a list of dicts from Google Sheets
            # CompilationProcessor.process_compilation expects this format
            output_url = await compilation_processor.process_compilation(comp_id, clips)
            
            if output_url:
                # Mark all rows in this compilation as done
                row_indices = [c['row_index'] for c in clips]
                google_sheets_service.mark_compilation_as_done(row_indices, output_url)
                logger.info(f"Compilation {comp_id} completed and marked as DONE.")
            else:
                logger.error(f"Compilation {comp_id} failed (no output URL).")
                
        except Exception as e:
            logger.error(f"Failed to process compilation {comp_id}: {e}")

async def run_compilation_sync_periodically():
    while True:
        try:
            await _process_pending_compilations()
        except Exception as e:
            logger.error(f"Error in compilation sync loop: {e}")
        
        await asyncio.sleep(settings.SHEETS_SYNC_INTERVAL_SECONDS)

def start_compilation_worker():
    def run_worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_compilation_sync_periodically())

    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()
    logger.info("Compilation sync worker started.")

def start_sheets_worker():
    def run_worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_sheets_sync_periodically())

    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()
    logger.info("Google Sheets sync worker started.")

def start_cleanup_worker():
    worker_thread = threading.Thread(target=cleanup_expired_files, daemon=True)
    worker_thread.start()
    logger.info("Cleanup worker started.")
