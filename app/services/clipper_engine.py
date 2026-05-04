import os
import cv2
import random
import mediapipe as mp
import numpy as np
import ffmpeg
import subprocess
import logging
from typing import List, Tuple, Optional, Dict
from app.services.audio_analyzer import get_audio_energy_map

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

    def get_split_centers(self, frame_bgr) -> Tuple[float, float, int]:
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

        if not faces_x: return (0.5, 0.5, 0)
        if len(faces_x) == 1: return (faces_x[0], faces_x[0], 1)
        
        faces_x.sort()
        return (faces_x[0], faces_x[-1], len(faces_x))

    def decide_layout(self, x_top: float, x_bot: float, face_count: int, last_mode: str, state_duration: float) -> str:
        """Intelligence Decision Engine for Layout Selection"""
        if face_count < 2:
            return "focus"
            
        dist = abs(x_top - x_bot)
        MIN_STATE_DURATION = 3.0 # Hysteresis: Stay in mode for at least 3s
        
        # 1. Proximity Thresholds
        target_mode = "split" if dist > 0.4 else "focus" # Slightly lower dist threshold for 2-face scenario
        
        # 2. Hysteresis Check
        if state_duration < MIN_STATE_DURATION:
            return last_mode
            
        return target_mode

    def analyze_video(self, video_path: str):
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps < 1: fps = 30 # Fallback
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
        
        # Stability Buffer for Split Mode
        MIN_SPLIT_CONFIRM_FRAMES = int(fps * 1.0) # 1 second stability
        split_face_buffer = 0
        
        logger.info(f"Starting Phase 2 AI Forensic Analysis: {video_path}")
        
        # Audio Energy Mapping
        energy_map = get_audio_energy_map(video_path)
        
        sample_interval = 1  # per-frame sampling for temporal consistency
        history_len = max(15, int(fps // 1.5)) # Higher history for strong inertia
        min_detection_delta = 0.03 # 3% Dead zone to prevent "wobbling"
        velocity_alpha = 0.15 # Softer velocity response
        max_velocity = 0.02 # Very smooth panning
        hold_frames_on_drop = max(15, int(fps * 0.75)) # Hold longer if lost
        top_hist: List[float] = [0.5]
        bot_hist: List[float] = [0.5]
        vel_top = 0.0
        vel_bot = 0.0
        lost_counter = 0

        while True:
            ret, frame = cap.read()
            if not ret: break
            
            if frame_idx % sample_interval == 0:
                if frame_idx % (fps * 5) == 0: # Log every 5 seconds of video processed
                    logger.info(f"[ANALYSIS] Processing AI tracking: frame {frame_idx}/{total_frames} ({(frame_idx/total_frames)*100:.1f}%)")
                
                current_time = frame_idx / fps
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # Motion Scoring
                motion_score = 0.0
                if last_frame_gray is not None:
                    diff = cv2.absdiff(gray, last_frame_gray)
                    motion_score = np.mean(diff) / 255.0
                last_frame_gray = gray
                
                # Dual Tracking
                raw_top, raw_bot, face_count = self.get_split_centers(frame)
                detection_valid = not (abs(raw_top - 0.5) < 1e-6 and abs(raw_bot - 0.5) < 1e-6)

                if face_count >= 2:
                    split_face_buffer = min(split_face_buffer + 1, MIN_SPLIT_CONFIRM_FRAMES)
                else:
                    split_face_buffer = max(0, split_face_buffer - 1)

                if not detection_valid:
                    lost_counter += 1
                else:
                    lost_counter = 0

                if detection_valid:
                    if abs(raw_top - last_x_top) < min_detection_delta:
                        raw_top = last_x_top
                    if abs(raw_bot - last_x_bot) < min_detection_delta:
                        raw_bot = last_x_bot
                elif lost_counter <= hold_frames_on_drop:
                    raw_top, raw_bot = last_x_top, last_x_bot
                else:
                    raw_top = last_x_top + vel_top
                    raw_bot = last_x_bot + vel_bot

                top_hist.append(raw_top)
                bot_hist.append(raw_bot)
                top_hist = top_hist[-history_len:]
                bot_hist = bot_hist[-history_len:]
                avg_top = float(np.mean(top_hist))
                avg_bot = float(np.mean(bot_hist))

                pred_top = last_x_top + vel_top
                pred_bot = last_x_bot + vel_bot
                target_top = (0.6 * avg_top) + (0.4 * pred_top)
                target_bot = (0.6 * avg_bot) + (0.4 * pred_bot)

                step_top = np.clip(target_top - last_x_top, -max_velocity, max_velocity)
                step_bot = np.clip(target_bot - last_x_bot, -max_velocity, max_velocity)
                x_top = float(np.clip(last_x_top + step_top, 0.0, 1.0))
                x_bot = float(np.clip(last_x_bot + step_bot, 0.0, 1.0))

                vel_top = (velocity_alpha * step_top) + ((1 - velocity_alpha) * vel_top)
                vel_bot = (velocity_alpha * step_bot) + ((1 - velocity_alpha) * vel_bot)
                
                # ── Phase 3: Audio-Visual Dominance ──
                # Check who is speaking by correlating audio energy with subject delta
                energy_idx = int(current_time / 0.1)
                audio_energy = energy_map[energy_idx] if energy_idx < len(energy_map) else 0.0
                
                # Swap top/bot if bot is significantly more "active" during high volume
                if audio_energy > 0.05 and face_count >= 2:
                    top_act = abs(step_top)
                    bot_act = abs(step_bot)
                    if bot_act > top_act * 1.5:
                        x_top, x_bot = x_bot, x_top # Swap focus
                
                # ── Phase 2: Decision Engine ──
                # Effective face_count for decision (must be stable)
                stable_face_count = face_count if split_face_buffer >= MIN_SPLIT_CONFIRM_FRAMES else (1 if face_count > 0 else 0)
                
                current_mode = self.decide_layout(x_top, x_bot, stable_face_count, last_mode, current_time - state_start_time)
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
        
        # Heavy Cinematic Smoothing (Rolling Window)
        window_size = 21 # Increased for rock-solid stability
        smoothed = [m.copy() for m in metadata]
        
        for key in ['x_top', 'x_bot']:
            values = [m[key] for m in metadata]
            for i in range(len(values)):
                start = max(0, i - window_size // 2)
                end = min(len(values), i + window_size // 2 + 1)
                window = values[start:end]
                smoothed[i][key] = sum(window) / len(window)
                
        return smoothed

    def _build_ease_expr(self, metadata: List[Dict], crop_w: int, original_width: int, target: str) -> str:
        if not metadata:
            return str(max(0, (original_width - crop_w) / 2))

        expr_parts = []
        for i in range(len(metadata) - 1):
            curr = metadata[i]
            nxt = metadata[i + 1]
            t_s, t_e = curr['time'], nxt['time']
            dt = max(1e-6, t_e - t_s)

            if target == 'focus':
                c_curr = (curr['x_top'] + curr['x_bot']) / 2
                c_next = (nxt['x_top'] + nxt['x_bot']) / 2
            else:
                c_curr = curr[target]
                c_next = nxt[target]

            p_curr = max(0, min(original_width - crop_w, c_curr * original_width - crop_w / 2))
            p_next = max(0, min(original_width - crop_w, c_next * original_width - crop_w / 2))
            delta = p_next - p_curr
            nt = f"((t-{t_s:.3f})/{dt:.6f})"
            ease = f"(3*pow({nt},2)-2*pow({nt},3))"  # smoothstep ease-in-out
            gate = f"gte(t,{t_s:.3f})*lt(t,{t_e:.3f})"
            expr_parts.append(f"(({p_curr:.3f})+({delta:.3f})*{ease})*{gate}")

        last = metadata[-1]
        if target == 'focus':
            c_last = (last['x_top'] + last['x_bot']) / 2
        else:
            c_last = last[target]

        p_last = max(0, min(original_width - crop_w, c_last * original_width - crop_w / 2))
        expr_parts.append(f"({p_last:.3f})*gte(t,{last['time']:.3f})")

        return " + ".join(expr_parts)

    def render(self, input_path: str, output_path: str, metadata: List[Dict], original_width: int, original_height: int, fps: float = 30.0, title: str = None, ass_path: str = None, anti_bot_vfx: bool = True, use_broll: bool = False):
        """
        Phase 2 Dynamic Render Engine:
        - Detects layout_mode changes
        - Toggles between Single Focus and Split Screen
        """
        hw_encoder = self._detect_hw_encoder()
        stream = ffmpeg.input(input_path)
        
        v_std = stream.video.filter('fps', fps=fps).filter('setpts', 'PTS-STARTPTS').filter('format', 'yuv420p')
        
        a_main = stream.audio.filter('asetpts', 'PTS-STARTPTS').filter('aresample', 48000).filter('loudnorm', I=-14, TP=-1, LRA=7)
        
        # 1. Prepare Tracking Expressions (Narrower for split to isolate faces)
        crop_w_split = int(original_height * (1080 / 960) * 0.8)
        crop_w_focus = int(original_height * (1080 / 1920))
        
        x_top_expr = self._build_ease_expr(metadata, crop_w_split, original_width, 'x_top')
        x_bot_expr = self._build_ease_expr(metadata, crop_w_split, original_width, 'x_bot')
        x_focus_expr = self._build_ease_expr(metadata, crop_w_focus, original_width, 'focus')

        # 2. Build Layer Nodes (Safe split syntax)
        splits1 = v_std.split()
        v_top_node = splits1[0]
        v_temp = splits1[1]
        
        splits2 = v_temp.split()
        v_bot_node = splits2[0]
        v_foc_node = splits2[1]

        v_top = v_top_node.filter('crop', crop_w_split, 'ih', x=x_top_expr, y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
        v_bot = v_bot_node.filter('crop', crop_w_split, 'ih', x=x_bot_expr, y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
        v_split_stack = ffmpeg.filter([v_top, v_bot], 'vstack')
        
        # Focus Layer (Single 9:16)
        v_focus = v_foc_node.filter('crop', crop_w_focus, 'ih', x=x_focus_expr, y=0).filter('scale', 1080, 1920, force_original_aspect_ratio='increase').filter('crop', 1080, 1920)

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
        video, audio = audio_engine.apply_bgm_with_ducking(video, a_main)
        
        import subprocess
        import time

        try:
            logger.info(f"Rendering Dynamic Phase 2 Output: {output_path}")
            vcodec_args = {'vcodec': hw_encoder, 'b:v': '10M'} if hw_encoder != 'libx264' else {'vcodec': 'libx264', 'crf': '19', 'preset': 'superfast'}
            
            output_node = ffmpeg.output(video, audio, output_path, **vcodec_args, acodec='aac', audio_bitrate='192k', map_metadata=-1)
            cmd = ffmpeg.compile(output_node.global_args('-fps_mode', 'cfr', '-r', str(fps), '-threads', '0'), overwrite_output=True)
            
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
