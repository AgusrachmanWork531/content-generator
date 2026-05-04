import logging
import os
import ffmpeg

logger = logging.getLogger(__name__)


class OverlayService:
    @staticmethod
    def apply_standard_overlays(video_stream, title: str = None):
        """
        Applies Title Card (first 4s), permanent watermark, and channel logo.
        """
        temp_files = []
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # 1. Title Card Card (0s - 4s)
        if title:
            # Using SheepingCats as a premium alternative since Doughsy is missing
            font_path = os.path.join(base_dir, "assets", "font", "sheeping-cats-font", "SheepingCats-929Z.ttf")
            if not os.path.exists(font_path):
                font_path = "Arial" # Fallback to Arial if folder is missing
            
            clean_title = title.upper().strip()
            video_stream = video_stream.filter(
                'drawtext',
                text=clean_title,
                fontfile=font_path,
                fontsize=85,
                fontcolor='white',
                borderw=4,
                bordercolor='black',
                shadowcolor='black@0.6',
                shadowx=4,
                shadowy=4,
                x='(w-text_w)/2',
                y='(h-text_h)/2-100',
                enable='between(t,0,4)'
            )

        # 2. Permanent Watermark Text "KILASAN VIDEO"
        arial_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
        if not os.path.exists(arial_path): arial_path = "Arial"

        video_stream = video_stream.filter(
            'drawtext',
            text='KILASAN VIDEO',
            fontcolor='white@0.35',
            fontsize=72,
            x='(w-text_w)/2',
            y='(h-text_h)/2',
            shadowcolor='black@0.3',
            shadowx=2,
            shadowy=2,
            fontfile=arial_path
        )

        # 2. Channel Logo (Top Right)
        # Calculate base directory (root of the project)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        logger.debug(f"Overlay base_dir: {base_dir}")
        
        logo_path = None
        for ext in ["png", "jpg", "jpeg"]:
            test_path = os.path.join(base_dir, "assets", f"logo.{ext}")
            if os.path.exists(test_path):
                logo_path = test_path
                break

        if logo_path:
            try:
                logger.info(f"Applying channel logo from: {logo_path}")
                # Use loop=1 for images (more efficient than stream_loop)
                logo_stream = ffmpeg.input(logo_path, loop=1)
                
                # Resize logo
                logo_stream = logo_stream.filter('scale', 140, -1)
                
                # Overlay on top right
                video_stream = ffmpeg.overlay(
                    video_stream, 
                    logo_stream, 
                    x='main_w-overlay_w-40', 
                    y='40',
                    shortest=1
                )
                logger.info("Successfully added logo overlay to the video stream.")
            except Exception as e:
                logger.error(f"Error applying logo overlay: {e}")
        else:
            logger.warning("No channel logo found in assets folder (logo.png/jpg/jpeg), skipping logo overlay.")

        return video_stream, temp_files


overlay_service = OverlayService()
