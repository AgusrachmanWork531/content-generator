import os
import uuid
import logging
from typing import List
from app.core.config import settings
from app.schemas.clip import ClipDownloadRequest
from app.services.youtube import download_youtube_clip, crop_video
from app.services.clipper_engine import ClipperEngine
from app.services.subtitle import subtitle_service
from app.services.youtube_upload import upload_short

logger = logging.getLogger(__name__)

def _to_sec(t):
    if not t: return 0
    if isinstance(t, (int, float)): return float(t)
    parts = str(t).split(':')
    if len(parts) == 3:
        return int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0])*60 + float(parts[1])
    return float(t)

class ClipProcessor:
    async def process_clip_v3(self, request: ClipDownloadRequest):
        """Main entry point called by the router."""
        intermediate_files = []
        output_file_id = str(uuid.uuid4())[:8]
        
        try:
            # ── Step 1: Download ──
            source_video = download_youtube_clip(request.url)
            source_path = os.path.join(settings.TMP_DIR, source_video)
            intermediate_files.append(source_path)

            # ── Step 2: Crop ──
            crop_filename = f"crop_clip_{output_file_id}.mp4"
            crop_path = os.path.join(settings.TMP_DIR, crop_filename)
            crop_video(source_path, crop_path, request.start_time, request.end_time)
            final_path = crop_path
            intermediate_files.append(crop_path)

            # ── Step 3: Thumbnail ──
            thumb_src = os.path.join(settings.TMP_DIR, f"thumb_{output_file_id}.jpg")
            try:
                import ffmpeg
                ffmpeg.input(final_path, ss=1.5).output(thumb_src, vframes=1).run(overwrite_output=True, quiet=True)
                intermediate_files.append(thumb_src)
            except Exception as te:
                logger.warning(f"Thumbnail failed: {te}")

            # ── Step 4: Auto-Reframe (SOTA Engine) ──
            if request.auto_reframe:
                logger.info(f"[{output_file_id}] Reframing video...")
                clipper = ClipperEngine()
                
                # Using the v3 method to avoid cache issues
                metadata, fps, width, height = clipper.analyze_video_v3(final_path)
                
                reframe_filename = f"reframe_{output_file_id}.mp4"
                reframe_path = os.path.join(settings.TMP_DIR, reframe_filename)
                
                ass_path = None
                if request.add_subtitles:
                    from app.services.youtube_transcript import youtube_transcript_service
                    transcript = youtube_transcript_service.get_transcript(request.url)
                    if transcript:
                        ass_path = os.path.join(settings.TMP_DIR, f"subs_{output_file_id}.ass")
                        s_sec = _to_sec(request.start_time)
                        e_sec = _to_sec(request.end_time)
                        subtitle_service.generate_ass(transcript, ass_path, start_time=s_sec, end_time=e_sec)
                        intermediate_files.append(ass_path)

                video_title = request.metaData.get('title') if request.metaData else "YouTube Short"
                clipper.render(
                    final_path, reframe_path, 
                    metadata, width, height, 
                    fps=fps,
                    title=video_title,
                    ass_path=ass_path,
                    anti_bot_vfx=request.anti_bot_vfx
                )
                final_path = reframe_path
                intermediate_files.append(reframe_path)

            # ── Step 5: Upload ──
            upload_result = None
            # CHECK: enable_youtube_upload column is the primary source
            should_upload = request.enable_youtube_upload
            if should_upload is None: # Fallback to platform check
                should_upload = (request.platform == "youtube")

            if should_upload:
                logger.info(f"[{output_file_id}] Upload toggle is ENABLED. Proceeding to YouTube...")
                upload_result = upload_short(final_path, request.metaData)
            else:
                logger.info(f"[{output_file_id}] Upload toggle is DISABLED. Skipping upload.")

            return {
                "status": "success",
                "file_id": os.path.basename(final_path),
                "upload_result": upload_result
            }

        except Exception as e:
            logger.error(f"[{output_file_id}] Pipeline crashed: {e}")
            raise e
        finally:
            pass

# Create instance
clip_processor = ClipProcessor()
process_clip_v3 = clip_processor.process_clip_v3
