import os
import uuid
import logging
import asyncio
from app.services.youtube import download_youtube_clip
from app.services.clipper_engine import ClipperEngine
from app.services.subtitle import subtitle_service
from app.services.youtube_upload import upload_short
from app.services.google_sheets import mark_row_done
from app.services.opening_narrator import generate_opening_video, merge_opening_and_short
from app.core.config import settings
from app.schemas.clip import ClipDownloadRequest, ClipItemResponse

logger = logging.getLogger(__name__)

async def process_clip_request(request: ClipDownloadRequest) -> ClipItemResponse:
    """
    Core pipeline to process a single clip:
    1. Download (yt-dlp)
    2. Crop (trim) or Multi-Segment Merge
    3. Auto-Thumbnail (Pillow 3D Title)
    4. Auto-Reframe (YOLO/MediaPipe tracking)
    5. Opening Narration (Edge-TTS)
    6. YouTube Upload
    """
    output_file_id = f"clip_{uuid.uuid4().hex[:8]}"
    final_path = None
    thumb_src = None
    intermediate_files: list[str] = []
    
    try:
        # ── Step 1: Download ──
        logger.info(f"[{output_file_id}] Downloading source: {request.url}")
        from app.services.youtube import download_youtube_clip, crop_video, concat_segments
        download_id = download_youtube_clip(request.url)
        if not download_id:
            return ClipItemResponse(status="error", message="Download failed")
            
        full_video_path = os.path.join(settings.TMP_DIR, download_id)
        intermediate_files.append(full_video_path)

        # ── Step 2: Crop (trim) or Multi-Segment Merge ──
        if request.auto_merge and getattr(request, 'segments', None):
            logger.info(f"[{output_file_id}] Auto-merge enabled with {len(request.segments)} segments.")
            seg_paths = []
            for i, seg in enumerate(request.segments):
                seg_id = f"{output_file_id}_seg{i}.mp4"
                seg_path = os.path.join(settings.TMP_DIR, seg_id)
                crop_video(full_video_path, seg_path, seg.start, seg.end)
                seg_paths.append(seg_path)
                intermediate_files.append(seg_path)
            
            merged_path = os.path.join(settings.TMP_DIR, f"merged_{output_file_id}.mp4")
            final_path = concat_segments(seg_paths, merged_path)
            intermediate_files.append(merged_path)
        else:
            # Traditional single crop
            crop_id = f"crop_{output_file_id}.mp4"
            crop_path = os.path.join(settings.TMP_DIR, crop_id)
            logger.info(f"[{output_file_id}] Cropping single segment: {request.start_time} - {request.end_time}")
            crop_video(full_video_path, crop_path, request.start_time, request.end_time)
            final_path = crop_path
            intermediate_files.append(crop_path)

        working_path = final_path # This is the landscape clip (merged or single)

        # ── Step 3: Auto-generate Premium Thumbnail (Pillow 3D Engine) ──
        try:
            from PIL import Image, ImageDraw, ImageFont
            import textwrap
            import ffmpeg

            thumb_src = os.path.join(settings.TMP_DIR, f"thumb_{output_file_id}.jpg")
            # Extract raw frame at 1.5s
            ffmpeg.input(working_path, ss=1.5).output(thumb_src, vframes=1).run(overwrite_output=True, quiet=True)
            
            # Apply 3D Title Overlay if metadata title exists
            title_raw = request.metaData.get('title') if request.metaData else "YouTube Short"
            if title_raw:
                img = Image.open(thumb_src)
                # 1. Cinematic Dark Overlay (33% opacity)
                overlay = Image.new('RGBA', img.size, (0, 0, 0, 85))
                img = img.convert('RGBA')
                img = Image.alpha_composite(img, overlay)
                draw = ImageDraw.Draw(img)
                
                # 2. Setup Font (Impact preferred)
                font_path = "/System/Library/Fonts/Supplemental/Impact.ttf"
                if not os.path.exists(font_path): font_path = None # Fallback to default
                
                font_size = 95
                title_font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
                
                # Wrap text
                wrapped_text = textwrap.fill(title_raw, width=16)
                
                # Calculate center position
                bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=title_font, align="center", spacing=4)
                w, h = img.size
                tx = (w - (bbox[2] - bbox[0])) / 2
                ty = (h - (bbox[3] - bbox[1])) / 2
                
                # 3. Draw 3D Drop Shadow (Offset)
                draw.multiline_text((tx+12, ty+15), wrapped_text, font=title_font, fill="black", align="center", spacing=4)
                # 4. Draw Main Text (White)
                draw.multiline_text((tx, ty), wrapped_text, font=title_font, fill="white", align="center", spacing=4, stroke_width=4, stroke_fill="black")
                
                img.convert('RGB').save(thumb_src, quality=95)
                logger.info(f"[{output_file_id}] Premium 3D Thumbnail generated.")
            
            intermediate_files.append(thumb_src)
        except Exception as te:
            logger.warning(f"[{output_file_id}] Failed to generate premium thumbnail: {te}")

        # ── Step 4: Auto-Reframe ──
        if request.auto_reframe:
            logger.info(f"[{output_file_id}] Reframing video...")
            clipper = ClipperEngine()
            centers, fps, width, height = clipper.analyze_video(final_path)
            smoothed = clipper.smooth_centers(centers)
            
            reframe_path = os.path.join(settings.TMP_DIR, f"reframe_{output_file_id}.mp4")
            
            # Subtitles
            ass_path = None
            if request.add_subtitles:
                from app.services.youtube_transcript import youtube_transcript_service
                transcript = youtube_transcript_service.get_transcript(request.url)
                if transcript:
                    ass_path = os.path.join(settings.TMP_DIR, f"subs_{output_file_id}.ass")
                    # Time filtering logic
                    from app.services.clip_processor import _to_sec # Use existing helper or define locally
                    s_sec = _to_sec(request.start_time)
                    e_sec = _to_sec(request.end_time)
                    subtitle_service.generate_ass(transcript, ass_path, start_time=s_sec, end_time=e_sec)
                    intermediate_files.append(ass_path)
            
            video_title = request.metaData.get('title') if request.metaData else None
            clipper.render(
                final_path, reframe_path, 
                smoothed, width, height, # Added height
                title=video_title,
                ass_path=ass_path, 
                anti_bot_vfx=request.anti_bot_vfx,
                use_broll=False # Hardcoded False
            )
            final_path = reframe_path
            intermediate_files.append(reframe_path)

        # ── Step 5: Opening Narration (Bypass Mode) ──
        bypass_intro_merge = True
        if not bypass_intro_merge and request.narration_text and request.narration_text.strip():
            logger.info(f"[{output_file_id}] Generating opening intro...")
            success, opening_path = await generate_opening_video(
                narration_text=request.narration_text.strip(),
                tmp_dir=str(settings.TMP_DIR),
                thumbnail_path=thumb_src
            )
            
            if success and opening_path:
                intermediate_files.append(opening_path)
                merged_intro_path = os.path.join(settings.TMP_DIR, f"final_v_{output_file_id}.mp4")
                merge_success = await merge_opening_and_short(opening_path, final_path, merged_intro_path)
                if merge_success:
                    final_path = merged_intro_path
                    intermediate_files.append(merged_intro_path)

        # ── Step 6: Upload ──
        upload_url = None
        if request.platform == "youtube" and (request.enable_youtube_upload or settings.ENABLE_YOUTUBE_UPLOAD):
            logger.info(f"[{output_file_id}] Uploading to YouTube...")
            upload_res = upload_short(final_path, request.metaData or {})
            upload_url = upload_res.get("url")
            
        if request.row_index:
            mark_row_done(request.row_index)
            
        # ── Step 7: Nuclear Cleanup ──
        # Purge all intermediate assets to save space, keeping ONLY the final video
        for f in intermediate_files:
            if f and f != final_path and os.path.exists(f):
                try: 
                    os.remove(f)
                    logger.debug(f"[{output_file_id}] Cleaned up: {os.path.basename(f)}")
                except Exception as ce: 
                    logger.warning(f"[{output_file_id}] Cleanup failed for {f}: {ce}")
                
        return ClipItemResponse(
            status="success",
            message="Processed and Cleaned Up (Pro-Grade)",
            file_id=output_file_id,
            download_url=f"/download/{os.path.basename(final_path)}",
            upload_url=upload_url
        )
        
    except Exception as e:
        logger.error(f"[{output_file_id}] Pipeline crashed: {e}")
        # Emergency Nuclear Cleanup: Attempt to delete everything on failure
        for f in intermediate_files:
            if f and os.path.exists(f):
                try: os.remove(f)
                except: pass
        return ClipItemResponse(status="error", message=str(e))

def _to_sec(t):
    if not t: return 0.0
    if isinstance(t, (int, float)): return float(t)
    try:
        parts = list(map(float, str(t).split(':')))
        if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
        if len(parts) == 2: return parts[0]*60 + parts[1]
        return parts[0]
    except: return 0.0
