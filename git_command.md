 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app/schemas/clip.py b/app/schemas/clip.py
index a4014d5..5d5f6e7 100644
--- a/app/schemas/clip.py
+++ b/app/schemas/clip.py
@@ -23,6 +23,7 @@ class ClipDownloadRequest(BaseModel):
     row_index: Optional[int] = None               # Original row index from Google Sheets
     anti_bot_vfx: bool = True                    # If True, adds subtle zoom/color shifts
     satisfying: bool = False                      # If True, adds B-roll split screen
+    auto_split: bool = False                      # If True, auto-pick best 15-60s segment
 
 class ClipItemResponse(BaseModel):
     status: str
diff --git a/app/services/clip_processor.py b/app/services/clip_processor.py
index 5e606e6..f93bd5b 100644
--- a/app/services/clip_processor.py
+++ b/app/services/clip_processor.py
@@ -8,6 +8,7 @@ from app.services.subtitle import subtitle_service
 from app.services.youtube_upload import upload_short
 from app.services.google_sheets import mark_row_done
 from app.services.opening_narrator import generate_opening_video, merge_opening_and_short
+from app.services.intelligent_splitter import IntelligentSplitter
 from app.core.config import settings
 from app.schemas.clip import ClipDownloadRequest, ClipItemResponse
 
@@ -52,6 +53,23 @@ async def process_clip_request(request: ClipDownloadRequest) -> ClipItemResponse
             merged_path = os.path.join(settings.TMP_DIR, f"merged_{output_file_id}.mp4")
             final_path = concat_segments(seg_paths, merged_path)
             intermediate_files.append(merged_path)
+        elif request.auto_split and not request.start_time and not request.end_time:
+            logger.info(f"[{output_file_id}] Intelligent auto-split enabled. Selecting best segment...")
+            transcript = None
+            try:
+                from app.services.youtube_transcript import youtube_transcript_service
+                transcript = youtube_transcript_service.get_transcript(request.url)
+            except Exception as te:
+                logger.warning(f"[{output_file_id}] Transcript fetch failed, fallback to AV-only split: {te}")
+
+            splitter = IntelligentSplitter(step_sec=0.1)
+            best = splitter.find_best_segment(full_video_path, transcript=transcript)
+            logger.info(f"[{output_file_id}] Best segment: {best.start:.2f}s - {best.end:.2f}s (score={best.score:.3f})")
+            crop_id = f"crop_{output_file_id}.mp4"
+            crop_path = os.path.join(settings.TMP_DIR, crop_id)
+            crop_video(full_video_path, crop_path, best.start, best.end)
+            final_path = crop_path
+            intermediate_files.append(crop_path)
         else:
             # Traditional single crop
             crop_id = f"crop_{output_file_id}.mp4"
diff --git a/app/services/clipper_engine.py b/app/services/clipper_engine.py
index a1b2c3d..e4f5g6h 100644
--- a/app/services/clipper_engine.py
+++ b/app/services/clipper_engine.py
@@ -1,11 +1,15 @@
 import os
 import cv2
 import random
 import mediapipe as mp
 import numpy as np
 import ffmpeg
 import subprocess
 import logging
+import supervision as sv
 from typing import List, Tuple, Optional, Dict
 from app.services.audio_analyzer import get_audio_energy_map
+from app.services.vad_service import build_speech_timeline, compute_turn_taking_score
+from app.services.cpd_service import find_split_boundaries
 
 logger = logging.getLogger(__name__)
@@ -51,6 +55,10 @@ class ClipperEngine:
             except Exception as e:
                 logger.error(f"YOLO Load Error: {e}")
+        
+        # ByteTrack Stability
+        self.tracker = sv.ByteTrack()
+        self.track_history = {} # track_id -> last_known_x
 
     def _detect_hw_encoder(self) -> str:
@@ -65,33 +73,43 @@ class ClipperEngine:
-    def get_split_centers(self, frame_bgr) -> Tuple[float, float, int]:
-        """Returns leftmost and rightmost X coordinates for Top-Bottom Split Screen"""
+    def get_split_centers(self, frame_bgr) -> Tuple[float, float, int, float]:
+        """Returns leftmost and rightmost X coordinates + face_count + avg bbox width (normalized)."""
         height, width, _ = frame_bgr.shape
         rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
-        faces_x = []
+        persons = []  # List of (x_center, bbox_width_norm)
 
         if self.detector:
             mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
             res = self.detector.detect(mp_image)
             if res.detections:
                 for detection in res.detections:
                     bbox = detection.bounding_box
-                    faces_x.append(float((bbox.origin_x + bbox.width / 2) / width))
-
-        if not faces_x and getattr(self, 'yolo_model', None):
+                    cx = float((bbox.origin_x + bbox.width / 2) / width)
+                    bw = float(bbox.width / width)
+                    persons.append((cx, bw))
+
+        if not persons and getattr(self, 'yolo_model', None):
             results = self.yolo_model.predict(frame_bgr, classes=[0], conf=0.35, verbose=False)
             if results and len(results[0].boxes) > 0:
-                boxes = results[0].boxes.xyxy.cpu().numpy()
-                for box in boxes:
-                    faces_x.append(float((box[0] + box[2]) / 2 / width))
-
-        if not faces_x: return (0.5, 0.5, 0)
-        if len(faces_x) == 1: return (faces_x[0], faces_x[0], 1)
-        
-        faces_x.sort()
-        return (faces_x[0], faces_x[-1], len(faces_x))
-
-    def decide_layout(self, x_top: float, x_bot: float, face_count: int, last_mode: str, state_duration: float) -> str:
-        """Intelligence Decision Engine for Layout Selection"""
+                # Convert to supervision detections for tracking
+                detections = sv.Detections.from_ultralytics(results[0])
+                detections = self.tracker.update_with_detections(detections)
+                
+                for i in range(len(detections)):
+                    box = detections.xyxy[i]
+                    track_id = detections.tracker_id[i] if detections.tracker_id is not None else i
+                    cx = float((box[0] + box[2]) / 2 / width)
+                    bw = float((box[2] - box[0]) / width)
+                    persons.append((cx, bw))
+                    self.track_history[track_id] = cx
+
+        if not persons: return (0.5, 0.5, 0, 0.0)
+        if len(persons) == 1: return (persons[0][0], persons[0][0], 1, persons[0][1])
+        
+        persons.sort(key=lambda p: p[0])
+        avg_bw = sum(p[1] for p in persons) / len(persons)
+        return (persons[0][0], persons[-1][0], len(persons), avg_bw)
+
+    def decide_layout(self, x_top: float, x_bot: float, face_count: int, avg_bbox_w: float, audio_conf: float, last_mode: str, state_duration: float) -> str:
+        """Intelligence Decision Engine for Layout Selection with Audio-Visual Validation."""
         if face_count < 2:
             return "focus"
-            
+        
         dist = abs(x_top - x_bot)
-        MIN_STATE_DURATION = 3.0 # Hysteresis: Stay in mode for at least 3s
-        
-        # 1. Proximity Thresholds
-        target_mode = "split" if dist > 0.4 else "focus" # Slightly lower dist threshold for 2-face scenario
-        
-        # 2. Hysteresis Check
+        MIN_STATE_DURATION = 3.0
+        
+        # Audio-Enhanced Overlap Guard
+        separation_multiplier = 1.0
+        if audio_conf > 0.6:
+            separation_multiplier = 0.85 # More lenient
+        elif audio_conf < 0.2:
+            separation_multiplier = 1.4  # More strict
+            
+        min_separation = max(0.25, avg_bbox_w * 1.5) * separation_multiplier
+        
+        if dist < min_separation:
+            return "focus"
+        
+        # Audio-based Trigger Threshold
+        split_threshold = 0.35 if audio_conf > 0.4 else 0.45
+        target_mode = "split" if dist > split_threshold else "focus"
+        
         if state_duration < MIN_STATE_DURATION:
             return last_mode
             
         return target_mode

-    def _compute_audio_split_confidence(self, energy_map: np.ndarray, current_time: float, window: float = 3.0) -> float:
-        """Calculates confidence that a dialogue is happening based on audio patterns."""
-        start_idx = max(0, int((current_time - window) / 0.1))
-        end_idx = int(current_time / 0.1)
-        segment = energy_map[start_idx:end_idx]
-        
-        if len(segment) < 10: return 0.5 # Neutral
-        
-        # 1. Turn-taking detection (zero-crossing around median)
-        threshold = np.median(segment)
-        crossings = np.sum(np.diff(segment > threshold))
-        turn_score = min(1.0, crossings / 12.0) # ~12 crossings in 3s is typical for active banter
-        
-        # 2. Variance (High variance often indicates alternating speakers/dynamic dialogue)
-        variance = np.var(segment)
-        var_score = min(1.0, variance / 0.008)
-        
-        # 3. Peak density (Dialogue has more frequent bursts than steady monolog)
-        peaks = np.sum(segment > (np.mean(segment) * 1.5))
-        peak_score = min(1.0, peaks / 8.0)
-        
-        return float(0.5 * turn_score + 0.3 * var_score + 0.2 * peak_score)
+    def _compute_audio_split_confidence(self, energy_map: np.ndarray, current_time: float, speech_tl: np.ndarray = None, turn_tl: np.ndarray = None, window: float = 3.0) -> float:
+        """
+        Calculates confidence that a dialogue is happening.
+        Uses Silero VAD speech timeline + turn-taking if available,
+        falls back to energy-based heuristic otherwise.
+        """
+        start_idx = max(0, int((current_time - window) / 0.1))
+        end_idx = int(current_time / 0.1)
+        
+        # --- VAD-Enhanced Path (Silero) ---
+        if speech_tl is not None and len(speech_tl) > end_idx and end_idx > start_idx:
+            speech_seg = speech_tl[start_idx:end_idx]
+            turn_seg = turn_tl[start_idx:end_idx] if turn_tl is not None and len(turn_tl) > end_idx else None
+            
+            if len(speech_seg) < 5:
+                return 0.5
+            
+            # 1. Speech density (how much of the window has speech)
+            speech_density = float(np.mean(speech_seg))
+            
+            # 2. Turn-taking score (from VAD-derived transitions)
+            if turn_seg is not None:
+                turn_score = float(np.mean(turn_seg))
+            else:
+                transitions = np.sum(np.abs(np.diff(speech_seg)))
+                turn_score = min(1.0, transitions / 8.0)
+            
+            # 3. Energy variance within speech regions
+            energy_seg = energy_map[start_idx:end_idx] if end_idx <= len(energy_map) else energy_map[start_idx:]
+            if len(energy_seg) > 0:
+                var_score = min(1.0, float(np.var(energy_seg)) / 0.006)
+            else:
+                var_score = 0.0
+            
+            # Weighted combination
+            return float(0.35 * speech_density + 0.40 * turn_score + 0.25 * var_score)
+        
+        # --- Fallback: Energy-only Path ---
+        segment = energy_map[start_idx:end_idx]
+        if len(segment) < 10:
+            return 0.5
+        
+        threshold = np.median(segment)
+        crossings = np.sum(np.diff(segment > threshold))
+        turn_score = min(1.0, crossings / 12.0)
+        variance = np.var(segment)
+        var_score = min(1.0, variance / 0.008)
+        peaks = np.sum(segment > (np.mean(segment) * 1.5))
+        peak_score = min(1.0, peaks / 8.0)
+        
+        return float(0.5 * turn_score + 0.3 * var_score + 0.2 * peak_score)

     def analyze_video(self, video_path: str):
@@ -118,7 +155,24 @@ class ClipperEngine:
-        logger.info(f"Starting Phase 2 AI Forensic Analysis: {video_path}")
+        logger.info(f"Starting Phase 3 AI Forensic Analysis: {video_path}")
         
         # Audio Energy Mapping
         energy_map = get_audio_energy_map(video_path)
+        
+        # Silero VAD Speech Timeline (replaces RMS heuristic)
+        video_duration = total_frames / fps
+        speech_timeline = build_speech_timeline(video_path, step_sec=0.1, duration=video_duration)
+        turn_taking = compute_turn_taking_score(speech_timeline, window_steps=30)
+        logger.info(f"[VAD] Speech timeline: {np.sum(speech_timeline > 0)} active steps / {len(speech_timeline)} total")
+        
+        # CPD Natural Boundaries (ruptures PELT)
+        energy_arr = np.array(energy_map, dtype=np.float32)
+        natural_boundaries = find_split_boundaries(
+            importance_score=energy_arr,
+            speech_timeline=speech_timeline,
+            step_sec=0.1,
+            penalty=10.0,
+            min_segment_sec=8.0
+        )
+        logger.info(f"[CPD] Natural split boundaries: {[f'{b:.1f}s' for b in natural_boundaries]}")
         
         sample_interval = 1  # per-frame sampling for temporal consistency
@@ -204,5 +258,8 @@ class ClipperEngine:
-                audio_conf = self._compute_audio_split_confidence(np.array(energy_map), current_time)
+                audio_conf = self._compute_audio_split_confidence(
+                    np.array(energy_map), current_time,
+                    speech_tl=speech_timeline, turn_tl=turn_taking
+                )
                 
-                current_mode = self.decide_layout(x_top, x_bot, stable_face_count, last_mode, current_time - state_start_time)
+                current_mode = self.decide_layout(
+                    x_top, x_bot, 
+                    stable_face_count, 
+                    last_avg_bbox_w, 
+                    audio_conf,
+                    last_mode, 
+                    current_time - state_start_time
+                )
diff --git a/app/services/intelligent_splitter.py b/app/services/intelligent_splitter.py
index a1b2c3d..e4f5g6h 100644
--- a/app/services/intelligent_splitter.py
+++ b/app/services/intelligent_splitter.py
@@ -82,17 +82,30 @@ class IntelligentSplitter:
         visual = self._visual_activity(video_path, target_steps)
         text = self._transcript_importance(transcript, target_steps)
 
-        # speech proxy from energy dynamics (VAD-lite)
-        speech = (energy > np.percentile(energy, 45)).astype(np.float32)
+        # Speech timeline from Silero VAD (falls back to energy proxy if unavailable)
+        try:
+            from app.services.vad_service import build_speech_timeline
+            speech = build_speech_timeline(video_path, step_sec=self.step_sec, duration=target_steps * self.step_sec)
+            if len(speech) < target_steps:
+                speech = np.pad(speech, (0, target_steps - len(speech)), mode="edge")
+            speech = speech[:target_steps]
+        except Exception:
+            speech = (energy > np.percentile(energy, 45)).astype(np.float32)
+
         context_shift = np.abs(np.diff(text, prepend=text[0]))
 
-        score = (
-            0.22 * self._z(energy)
-            + 0.18 * self._z(speech)
-            + 0.30 * self._z(text + 1e-3)
-            + 0.20 * self._z(visual + 1e-3)
-            + 0.10 * self._z(context_shift + 1e-3)
-        )
+        # Use CPD-enhanced importance scoring if available
+        try:
+            from app.services.cpd_service import build_importance_score
+            score = build_importance_score(energy, speech, visual, text)
+        except Exception:
+            score = (
+                0.22 * self._z(energy)
+                + 0.18 * self._z(speech)
+                + 0.30 * self._z(text + 1e-3)
+                + 0.20 * self._z(visual + 1e-3)
+                + 0.10 * self._z(context_shift + 1e-3)
+            )
diff --git a/app/services/vad_service.py b/app/services/vad_service.py
new file mode 100644
index 0000000..f9b8076
--- /dev/null
+++ b/app/services/vad_service.py
@@ -0,0 +1,100 @@
+import logging
+import subprocess
+import tempfile
+import os
+import numpy as np
+
+logger = logging.getLogger(__name__)
+... (Isi vad_service.py)
+diff --git a/app/services/cpd_service.py b/app/services/cpd_service.py
+new file mode 100644
+index 0000000..f9b8076
+--- /dev/null
++++ b/app/services/cpd_service.py
+@@ -0,0 +1,120 @@
+import logging
+import numpy as np
+... (Isi cpd_service.py)
+diff --git a/requirements.txt b/requirements.txt
+index a1b2c3d..e4f5g6h 100644
+--- a/requirements.txt
++++ b/requirements.txt
+@@ -18,3 +18,6 @@ static-ffmpeg
+ scenedetect
+ edge-tts
++silero-vad-lite
++ruptures
++supervision
+
+EOF
+)
+