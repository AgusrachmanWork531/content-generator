import os
import cv2
import random
import mediapipe as mp
import numpy as np
import ffmpeg
import subprocess
import logging
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)

try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False

from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from app.services.overlay import overlay_service
from app.services.audio_engine import audio_engine
from app.services.proximity_analyzer import ProximityAnalyzer
from app.core.config import settings

class ClipperEngine:
    def __init__(self, smoothing_factor: float = 0.08):
        self.smoothing_factor = smoothing_factor
        self.aspect_ratio = 9/16
        self.proximity = ProximityAnalyzer(base_proximity=0.5)
        
        # Setup MediaPipe Fallback
        model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "models", "face_detector.tflite")
        if not os.path.exists(model_path):
            self.detector = None
        else:
            base_options = python.BaseOptions(model_asset_path=model_path)
            options = vision.FaceDetectorOptions(base_options=base_options)
            self.detector = vision.FaceDetector.create_from_options(options)

        # Setup YOLO Primary
        self.yolo_model = None
        if HAS_YOLO:
            try:
                self.yolo_model = YOLO("yolo11n.pt")
                try:
                    self.yolo_model.to("mps")
                except:
                    pass
            except Exception as e:
                logger.error(f"YOLO Load Error: {e}")

    def _detect_hw_encoder(self) -> str:
        candidates = ['h264_videotoolbox', 'h264_nvenc']
        try:
            result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True, check=False)
            for encoder in candidates:
                if encoder in result.stdout:
                    return encoder
        except:
            pass
        return 'libx264'

    def get_split_centers(self, frame_bgr) -> Tuple[float, float]:
        """Returns leftmost and rightmost X coordinates for Top-Bottom Split Screen"""
        height, width, _ = frame_bgr.shape
        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        faces_x = []

        if self.detector:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            res = self.detector.detect(mp_image)
            if res.detections:
                for detection in res.detections:
                    bbox = detection.bounding_box
                    faces_x.append(float((bbox.origin_x + bbox.width / 2) / width))

        if not faces_x and getattr(self, 'yolo_model', None):
            results = self.yolo_model.predict(frame_bgr, classes=[0], conf=0.35, verbose=False)
            if results and len(results[0].boxes) > 0:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                for box in boxes:
                    faces_x.append(float((box[0] + box[2]) / 2 / width))

        if not faces_x: return (0.5, 0.5)
        if len(faces_x) == 1: return (faces_x[0], faces_x[0])
        
        faces_x.sort()
        return (faces_x[0], faces_x[-1])

    def decide_layout(self, x_top: float, x_bot: float, last_mode: str, state_duration: float) -> str:
        """Intelligence Decision Engine for Layout Selection"""
        dist = abs(x_top - x_bot)
        MIN_STATE_DURATION = 3.0 # Hysteresis: Stay in mode for at least 3s
        
        # 1. Proximity Thresholds
        target_mode = "split" if dist > 0.5 else "focus"
        
        # 2. Hysteresis Check
        if state_duration < MIN_STATE_DURATION:
            return last_mode
            
        return target_mode

    def analyze_video(self, video_path: str):
        cap = cv2.VideoCapture(video_path)
        fps = 30
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        metadata = []
        frame_idx = 0
        last_x_top, last_x_bot = 0.5, 0.5
        last_mode = "focus"
        state_start_time = 0.0
        last_frame_gray = None
        DEAD_ZONE = 0.05
        
        logger.info(f"Starting Phase 2 AI Forensic Analysis: {video_path}")
        
        while True:
            ret, frame = cap.read()
            if not ret: break
            
            if frame_idx % int(fps) == 0:
                current_time = frame_idx / fps
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # Motion Scoring
                motion_score = 0.0
                if last_frame_gray is not None:
                    diff = cv2.absdiff(gray, last_frame_gray)
                    motion_score = np.mean(diff) / 255.0
                last_frame_gray = gray
                
                # Dual Tracking
                x_top, x_bot = self.get_split_centers(frame)
                
                if abs(x_top - last_x_top) < DEAD_ZONE: x_top = last_x_top
                if abs(x_bot - last_x_bot) < DEAD_ZONE: x_bot = last_x_bot
                
                # ── Phase 2: Decision Engine ──
                current_mode = self.decide_layout(x_top, x_bot, last_mode, current_time - state_start_time)
                if current_mode != last_mode:
                    state_start_time = current_time
                    last_mode = current_mode
                
                last_x_top, last_x_bot = x_top, x_bot
                importance = min(1.0, (motion_score * 5.0) + 0.5) 
                
                metadata.append({
                    "time": current_time,
                    "x_top": float(x_top),
                    "x_bot": float(x_bot),
                    "layout_mode": current_mode,
                    "importance": float(importance),
                    "is_peak": importance > 0.8
                })
            
            frame_idx += 1
            if frame_idx >= total_frames: break
                
        cap.release()
        return metadata, fps, width, height

    def smooth_centers(self, metadata: List[Dict]):
        if not metadata: return []
        smooth_f = 0.15
        smoothed = [m.copy() for m in metadata]
        for i in range(1, len(metadata)):
            smoothed[i]['x_top'] = smooth_f * metadata[i]['x_top'] + (1 - smooth_f) * smoothed[i-1]['x_top']
            smoothed[i]['x_bot'] = smooth_f * metadata[i]['x_bot'] + (1 - smooth_f) * smoothed[i-1]['x_bot']
        return smoothed

    def render(self, input_path: str, output_path: str, metadata: List[Dict], original_width: int, original_height: int, title: str = None, ass_path: str = None, anti_bot_vfx: bool = True, use_broll: bool = False):
        """
        Phase 2 Dynamic Render Engine:
        - Detects layout_mode changes
        - Toggles between Single Focus and Split Screen
        """
        hw_encoder = self._detect_hw_encoder()
        stream = ffmpeg.input(input_path)
        
        v_std = stream.video.filter('fps', fps=30).filter('setpts', 'PTS-STARTPTS').filter('format', 'yuv420p')
        
        a_main = stream.audio.filter('asetpts', 'PTS-STARTPTS').filter('aresample', 48000).filter('loudnorm', I=-14, TP=-1, LRA=7)
        
        # 1. Prepare Tracking Expressions
        crop_w_split = int(original_height * (1080 / 960))
        crop_w_focus = int(original_height * (1080 / 1920))
        
        x_top_expr, x_bot_expr, x_focus_expr = [], [], []
        for i in range(len(metadata) - 1):
            t_s, t_e = metadata[i]['time'], metadata[i+1]['time']
            p_top = max(0, min(original_width - crop_w_split, metadata[i]['x_top'] * original_width - crop_w_split/2))
            p_bot = max(0, min(original_width - crop_w_split, metadata[i]['x_bot'] * original_width - crop_w_split/2))
            p_foc = max(0, min(original_width - crop_w_focus, ((metadata[i]['x_top'] + metadata[i]['x_bot'])/2) * original_width - crop_w_focus/2))
            
            # Use half-open time windows [t_s, t_e) so exactly one segment is active.
            # `between()` is inclusive on both ends and can cause one-frame overlaps,
            # producing a sudden x-position spike (visual glitch) at segment boundaries.
            gate = f"gte(t,{t_s:.3f})*lt(t,{t_e:.3f})"
            x_top_expr.append(f"{p_top}*{gate}")
            x_bot_expr.append(f"{p_bot}*{gate}")
            x_focus_expr.append(f"{p_foc}*{gate}")

        if metadata:
            last = metadata[-1]
            p_top = max(0, min(original_width - crop_w_split, last['x_top'] * original_width - crop_w_split/2))
            p_bot = max(0, min(original_width - crop_w_split, last['x_bot'] * original_width - crop_w_split/2))
            p_foc = max(0, min(original_width - crop_w_focus, ((last['x_top'] + last['x_bot'])/2) * original_width - crop_w_focus/2))
            x_top_expr.append(f"{p_top}*gte(t,{last['time']:.3f})")
            x_bot_expr.append(f"{p_bot}*gte(t,{last['time']:.3f})")
            x_focus_expr.append(f"{p_foc}*gte(t,{last['time']:.3f})")
        else:
            # Metadata bisa kosong jika analisis gagal; gunakan center crop agar FFmpeg tetap valid.
            default_top = max(0, (original_width - crop_w_split) / 2)
            default_foc = max(0, (original_width - crop_w_focus) / 2)
            x_top_expr.append(str(default_top))
            x_bot_expr.append(str(default_top))
            x_focus_expr.append(str(default_foc))

        # 2. Build Layer Nodes (Safe split syntax)
        splits1 = v_std.split()
        v_top_node = splits1[0]
        v_temp = splits1[1]
        
        splits2 = v_temp.split()
        v_bot_node = splits2[0]
        v_foc_node = splits2[1]

        v_top = v_top_node.filter('crop', crop_w_split, 'ih', x=" + ".join(x_top_expr), y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
        v_bot = v_bot_node.filter('crop', crop_w_split, 'ih', x=" + ".join(x_bot_expr), y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
        v_split_stack = ffmpeg.filter([v_top, v_bot], 'vstack')
        
        # Focus Layer (Single 9:16)
        v_focus = v_foc_node.filter('crop', crop_w_focus, 'ih', x=" + ".join(x_focus_expr), y=0).filter('scale', 1080, 1920, force_original_aspect_ratio='increase').filter('crop', 1080, 1920)

        # 3. Dynamic Switcher (Single Overlay Logic)
        # Combine all split segments into one expression to avoid multiple outgoing edges
        split_ranges = []
        if metadata:
            curr_mode = metadata[0]['layout_mode']
            start_t = metadata[0]['time']
            for m in metadata:
                if m['layout_mode'] != curr_mode:
                    if curr_mode == 'split':
                        split_ranges.append(f"gte(t,{start_t:.3f})*lt(t,{m['time']:.3f})")
                    curr_mode = m['layout_mode']
                    start_t = m['time']
            if curr_mode == 'split':
                split_ranges.append(f"gte(t,{start_t:.3f})")

        video = v_focus
        if split_ranges:
            combined_enable = "+".join(split_ranges)
            video = ffmpeg.filter([video, v_split_stack], 'overlay', enable=combined_enable)

        if ass_path and os.path.exists(ass_path):
            video = video.filter('ass', os.path.abspath(ass_path))
            
        video = video.filter('drawtext', text='KILASAN VIDEO', fontcolor='white', alpha=0.5, fontsize=40, x='(w-text_w)/2', y='(h-text_h)/2 + 200')
        if title:
            video = video.filter('drawtext', text=title.upper(), fontcolor='white', borderw=4, bordercolor='black', fontsize=75, x='(w-text_w)/2', y='(h-text_h)/2')
            
        video, audio = audio_engine.apply_bgm_with_ducking(video, a_main)
        
        import subprocess
        import time

        try:
            logger.info(f"Rendering Dynamic Phase 2 Output: {output_path}")
            vcodec_args = {'vcodec': hw_encoder, 'b:v': '10M'} if hw_encoder != 'libx264' else {'vcodec': 'libx264', 'crf': '19', 'preset': 'superfast'}
            
            output_node = ffmpeg.output(video, audio, output_path, **vcodec_args, acodec='aac', audio_bitrate='192k', map_metadata=-1)
            cmd = ffmpeg.compile(output_node.global_args('-fps_mode', 'cfr', '-r', '30', '-threads', '0'), overwrite_output=True)
            
            logger.info("Memulai proses render. Silakan tunggu...")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            
            start_time = time.time()
            for line in process.stdout:
                if "time=" in line:
                    try:
                        time_str = line.split("time=")[1].split(" ")[0]
                        elapsed = int(time.time() - start_time)
                        if elapsed % 5 == 0:
                            logger.info(f"[LOADING] Rendering progress: Waktu video diproses -> {time_str}")
                    except Exception:
                        pass
            
            process.wait()
            if process.returncode != 0:
                raise Exception(f"FFmpeg failed with exit code {process.returncode}")
                
            logger.info(f"✅ Dynamic Render Complete: {output_path}")
        except Exception as e:
            logger.error(f"❌ Dynamic Render Failed: {e}")
            raise e
