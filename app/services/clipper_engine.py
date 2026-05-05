import os
import cv2
import subprocess
import numpy as np
import logging
import tempfile
from typing import List, Dict, Optional, Tuple

from ultralytics import YOLO
from app.core.config import settings

logger = logging.getLogger(__name__)

ASPECT_RATIO = 9 / 16

# ─── Lazy-loaded singletons ───────────────────────────────────────────────────

_yolo_model = None
_face_cascade = None
_mp_face_mesh = None

def _get_yolo():
    global _yolo_model
    if _yolo_model is None:
        _yolo_model = YOLO("yolo11n.pt")
        try:
            _yolo_model.to("mps")
            logger.info("🚀 YOLOv11 loaded on Apple Silicon (MPS).")
        except Exception:
            logger.warning("MPS unavailable — using CPU for YOLO.")
    return _yolo_model

def _get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _face_cascade

def _get_face_mesh():
    global _mp_face_mesh
    if _mp_face_mesh is None:
        try:
            # Multi-stage import fallback for MediaPipe
            try:
                import mediapipe.solutions.face_mesh as mp_face_mesh
            except (ImportError, AttributeError):
                try:
                    from mediapipe.python.solutions import face_mesh as mp_face_mesh
                except (ImportError, AttributeError):
                    import mediapipe as mp
                    mp_face_mesh = mp.solutions.face_mesh

            _mp_face_mesh = mp_face_mesh.FaceMesh(
                static_image_mode=True, max_num_faces=1, refine_landmarks=True,
                min_detection_confidence=0.5
            )
        except Exception as exc:
            logger.warning(f"MediaPipe face mesh unavailable ({exc}). Active speaker detection disabled.")
            return None
    return _mp_face_mesh


# ─── Scene Detection ──────────────────────────────────────────────────────────

def _detect_scenes(video_path: str) -> List[Tuple[int, int]]:
    """
    Returns list of (start_frame, end_frame) tuples using PySceneDetect.
    Falls back to a single scene covering the whole video if unavailable.
    """
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector

        video = open_video(video_path)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector())
        scene_manager.detect_scenes(video, show_progress=False)
        raw = scene_manager.get_scene_list()

        if raw:
            return [(s.get_frames(), e.get_frames()) for s, e in raw]
    except Exception as exc:
        logger.warning(f"PySceneDetect unavailable ({exc}). Treating video as one scene.")

    # Fallback: entire video is one scene
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return [(0, total)]


# ─── Content Analysis ─────────────────────────────────────────────────────────

def _analyze_scene_frame(frame: np.ndarray) -> List[Dict]:
    """
    Runs YOLOv11 (person class=0) on a single frame.
    For each detected person, attempts Haar Cascade face detection and 
    MediaPipe mouth tracking to score activity.
    """
    model = _get_yolo()
    results = model([frame], classes=[0], conf=0.3, verbose=False)[0]
    face_mesh = _get_face_mesh()

    detected = []
    for box in results.boxes:
        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
        person_box = [x1, y1, x2, y2]

        face_box = None
        mouth_score = 0.0
        roi = frame[y1:y2, x1:x2]
        
        if roi.size > 0:
            # 1. Haar Cascade Face Detection
            gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            faces = _get_face_cascade().detectMultiScale(
                gray_roi, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            if len(faces) > 0:
                fx, fy, fw, fh = faces[0]
                face_box = [x1 + fx, y1 + fy, x1 + fx + fw, y1 + fy + fh]

                # 2. Mouth Opening Detection (Active Speaker Score)
                if face_mesh:
                    face_roi = roi[fy:fy+fh, fx:fx+fw]
                    if face_roi.size > 0:
                        rgb_face = cv2.cvtColor(face_roi, cv2.COLOR_BGR2RGB)
                        fm_results = face_mesh.process(rgb_face)
                        if fm_results.multi_face_landmarks:
                            lm = fm_results.multi_face_landmarks[0].landmark
                            # Inner lips: 13 (upper), 14 (lower)
                            dist = abs(lm[13].y - lm[14].y)
                            mouth_score = float(dist)

        detected.append({
            "person_box": person_box, 
            "face_box": face_box,
            "active_score": mouth_score
        })

    return detected


def _get_enclosing_box(boxes: List[List[int]]) -> Optional[List[int]]:
    if not boxes:
        return None
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _best_face_target(det: Dict) -> List[int]:
    """
    Fix #1 — Face-First Box Selection.
    Priority: face_box → head-region estimate (top 25% of person_box) → person_box center.
    Prevents crop from centering on torso/legs when face is not detected.
    """
    if det["face_box"]:
        return det["face_box"]
    pb = det["person_box"]
    person_h = pb[3] - pb[1]
    # Estimate head region as top 25% of person bounding box
    head_h = max(int(person_h * 0.25), 10)
    return [pb[0], pb[1], pb[2], pb[1] + head_h]


def _decide_strategy(
    detections: List[Dict], frame_height: int
) -> Tuple[str, Optional[any]]:
    """
    Returns ('TRACK', target_box), ('SPLIT', detections), or ('LETTERBOX', None).
    TRACK  — crop tightly around person/face.
    SPLIT  — two people detected; split frame vertically.
    LETTERBOX — people too spread; preserve full frame with black bars.
    """
    n = len(detections)
    if n == 0:
        return "LETTERBOX", None
    if n == 1:
        target = detections[0]["face_box"] or detections[0]["person_box"]
        return "TRACK", target

    # Multiple people: check if group fits within crop width
    person_boxes = [d["person_box"] for d in detections]
    group_box = _get_enclosing_box(person_boxes)
    group_width = group_box[2] - group_box[0]
    max_crop_width = frame_height * ASPECT_RATIO
    if group_width < max_crop_width:
        return "TRACK", group_box
    
    # Split frame for 2 people if they are too far apart
    if n >= 2:
        # Sort by active_score (descending) then horizontal position
        # This prioritizes the speaker for the "First" detection (top panel)
        sorted_dets = sorted(detections, key=lambda d: (d.get("active_score", 0), -d["person_box"][0]), reverse=True)
        candidates = sorted_dets[:2]
        
        # Keep horizontal order for the actual candidates to avoid flipping sides 
        # but the first one in this list will be the "Focus" panel (Top)
        return "SPLIT", candidates

    return "LETTERBOX", None


def _calculate_crop_box(
    target_box: List[int], frame_width: int, frame_height: int, 
    prev_cx: float, prev_cy: float, alpha: float = 0.12
) -> Tuple[int, int, int, int, float, float]:
    """
    Computes (x1, y1, x2, y2) with Digital Zoom, EMA smoothing and Face Y-anchoring.
    """
    # 0. Digital Zoom Configuration (1.15x zoom to allow centering edge subjects)
    zoom_factor = 1.15
    
    # 1. Calculate Raw Target
    target_cx = (target_box[0] + target_box[2]) / 2 / frame_width
    # Use center Y (not top edge) to prevent upward drift/out-of-frame crops
    target_cy = ((target_box[1] + target_box[3]) / 2) / frame_height

    # 2. Apply EMA Smoothing
    new_cx = (alpha * target_cx) + (1 - alpha) * prev_cx
    new_cy = (alpha * target_cy) + (1 - alpha) * prev_cy

    # 3. Calculate Crop Window with Zoom
    # We crop a smaller area and then resize to target_height
    crop_h = int(frame_height / zoom_factor)
    crop_w = int(crop_h * ASPECT_RATIO)

    # Hard guard: never allow crop box larger than source frame
    crop_w = min(crop_w, frame_width)
    crop_h = min(crop_h, frame_height)
    
    # X-axis clamping with margin enforcement
    x1 = int(new_cx * frame_width - crop_w / 2)
    if x1 < 0: x1 = 0
    if x1 + crop_w > frame_width: x1 = max(0, frame_width - crop_w)
    x2 = x1 + crop_w

    # Y-axis Framing (Face Y-Anchor at 30%)
    face_y_in_frame = new_cy * frame_height
    y1 = int(face_y_in_frame - (crop_h * 0.30))
    if y1 < 0: y1 = 0
    if y1 + crop_h > frame_height: y1 = max(0, frame_height - crop_h)
    y2 = y1 + crop_h

    return x1, y1, x2, y2, new_cx, new_cy


def _fill_with_blur(frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """
    Fills a canvas of (target_w, target_h) with a blurred version of 'frame' 
    then overlays the best possible fit of 'frame' in the center.
    """
    # 1. Create blurred background
    bg = cv2.resize(frame, (target_w, target_h))
    bg = cv2.GaussianBlur(bg, (51, 51), 0)
    
    # 2. Scale frame to fit
    fh, fw = frame.shape[:2]
    aspect = fw / fh
    target_aspect = target_w / target_h
    
    if aspect > target_aspect:
        # Frame is wider than target: scale by width
        nw = target_w
        nh = int(nw / aspect)
    else:
        # Frame is taller than target: scale by height
        nh = target_h
        nw = int(nh * aspect)
        
    scaled = cv2.resize(frame, (nw, nh))
    
    # 3. Overlay
    y_off = (target_h - nh) // 2
    x_off = (target_w - nw) // 2
    bg[y_off : y_off + nh, x_off : x_off + nw] = scaled
    return bg


# ─── Audio Helpers ────────────────────────────────────────────────────────────

def _has_audio(video_path: str) -> bool:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path],
            capture_output=True, text=True,
        )
        return r.returncode == 0 and "audio" in r.stdout
    except FileNotFoundError:
        return True


def _get_stream_start(video_path: str, stream: str = "v:0") -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", stream,
             "-show_entries", "stream=start_time", "-of", "csv=p=0", video_path],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except (FileNotFoundError, ValueError):
        pass
    return 0.0


# ─── Main Engine ──────────────────────────────────────────────────────────────

class ClipperEngine:
    """
    Autocrop-Vertical-style vertical reframing engine.
    Pipeline:
      1. Scene detection (PySceneDetect / fallback)
      2. Per-scene content analysis (YOLOv11 + Haar Cascade)
      3. Strategy decision  → TRACK or LETTERBOX
      4. Frame-by-frame OpenCV processing, piped to FFmpeg (hw-accelerated)
      5. Audio re-merge with start-time offset correction
    """

    # Fix #5 — Hysteresis constants
    _STRATEGY_MIN_HOLD = 30  # ~1s at 30fps before strategy switch allowed
    _SPLIT_SEPARATOR_PX = 4  # black separator between split panels

    def __init__(self):
        self.smoothing_factor = 0.12
        self.prev_cx = 0.5
        self.prev_cy = 0.3
        self.hw_encoder = "h264_videotoolbox"
        # Hysteresis state
        self._last_strategy = "LETTERBOX"
        self._last_target = None
        self._strategy_hold_frames = 0

    # ── Public API (matches existing callers) ─────────────────────────────────

    def analyze_video_v3(self, video_path: str):
        """
        Returns (scene_plan, fps, width, height).
        scene_plan: list of per-scene dicts with strategy + crop info.
        """
        cap = cv2.VideoCapture(video_path)
        fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        logger.info(f"🔍 Autocrop Analysis: {video_path} ({width}x{height} @ {fps:.1f}fps, {total} frames)")

        # Step 1 — Detect scenes
        scenes = _detect_scenes(video_path)
        logger.info(f"📽️  Detected {len(scenes)} scene(s).")

        # Step 2 & 3 — Analyse middle frame per scene → decide strategy
        cap = cv2.VideoCapture(video_path)
        scene_plan = []
        for idx, (sf, ef) in enumerate(scenes):
            mid = (sf + ef) // 2
            cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
            ret, frame = cap.read()
            detections = _analyze_scene_frame(frame) if ret else []
            strategy, target_box = _decide_strategy(detections, height)

            scene_plan.append({
                "start_frame": sf,
                "end_frame":   ef,
                "strategy":    strategy,
                "target_box":  target_box,
                "n_persons":   len(detections),
            })

            pct = int((idx + 1) / len(scenes) * 100)
            logger.info(
                f"  Scene {idx+1}/{len(scenes)} (frames {sf}-{ef}): "
                f"{len(detections)} person(s) → {strategy} [{pct}%]"
            )
        cap.release()

        return scene_plan, fps, width, height

    def render(
        self,
        input_path: str,
        output_path: str,
        scene_plan: List[Dict],
        width: int,
        height: int,
        fps: float,
        title: str = None,
        ass_path: str = None,
        anti_bot_vfx: bool = True,
        use_broll: bool = False,
    ):
        """
        Frame-accurate render: OpenCV reads frames → piped to FFmpeg.
        Follows Autocrop-vertical v1.4 architecture for accuracy + stability.
        """
        logger.info(f"🎬 Rendering with {self.hw_encoder} (frame-pipe mode)…")

        out_w = int(height * ASPECT_RATIO)
        if out_w % 2 != 0:
            out_w += 1
        out_h = height
        if out_h % 2 != 0:
            out_h += 1

        tmp_dir = os.path.dirname(output_path)
        base     = os.path.splitext(output_path)[0]
        tmp_vid  = base + "_tmpvid.mp4"
        tmp_aud  = base + "_tmpaud.mkv"

        # ── Step 4: Frame-by-frame processing ────────────────────────────────
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{out_w}x{out_h}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",
            "-c:v", self.hw_encoder,
            "-b:v", "8M", "-allow_sw", "1",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-vsync", "cfr",
            "-an", tmp_vid,
        ]

        proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        cap = cv2.VideoCapture(input_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_number = 0
        scene_idx    = 0
        last_frame   = None

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Advance scene index
            while (
                scene_idx < len(scene_plan) - 1
                and frame_number >= scene_plan[scene_idx + 1]["start_frame"]
            ):
                scene_idx += 1

            scene = scene_plan[scene_idx]

            # Fix #5 — Hysteresis guard: hold current strategy for min frames
            # Logic: If scene strategy differs from current state, increment counter.
            # Once counter hits threshold, perform the switch.
            if scene["strategy"] != self._last_strategy:
                self._strategy_hold_frames += 1
                if self._strategy_hold_frames >= self._STRATEGY_MIN_HOLD:
                    self._last_strategy = scene["strategy"]
                    self._last_target   = scene["target_box"]
                    self._strategy_hold_frames = 0
            else:
                # Same strategy: always update target to current scene's target box
                # (prevents using old scene's target during consecutive TRACK scenes)
                self._last_target = scene["target_box"]
                self._strategy_hold_frames = 0

            effective_strategy = self._last_strategy
            effective_target   = self._last_target

            try:
                if effective_strategy == "TRACK" and effective_target:
                    x1, y1, x2, y2, self.prev_cx, self.prev_cy = _calculate_crop_box(
                        effective_target, width, height,
                        self.prev_cx, self.prev_cy
                    )
                    cropped = frame[y1:y2, x1:x2]
                    output_frame = cv2.resize(cropped, (out_w, out_h))
                elif effective_strategy == "SPLIT" and isinstance(effective_target, list):
                    # Fix #3 & #4 — Adaptive crop dimensions (55% of source height)
                    sep    = self._SPLIT_SEPARATOR_PX
                    panel_1_h = (out_h - sep) // 2
                    panel_2_h = out_h - sep - panel_1_h
                    panels = []
                    panel_heights = [panel_1_h, panel_2_h]

                    for i in range(min(2, len(effective_target))):
                        det = effective_target[i]
                        # Fix #1 — Face-first box selection with head-region fallback
                        tbox = _best_face_target(det)

                        # Target center
                        tcx = (tbox[0] + tbox[2]) / 2
                        tcy_raw = (tbox[1] + tbox[3]) / 2

                        ph = panel_heights[i]
                        # Fix #3 — sc_h = 55% of source height for natural zoom
                        sc_h = int(height * 0.55)
                        sc_h = min(sc_h, height)
                        # Fix #4 — sc_w consistent with output panel aspect ratio
                        sc_w = int(sc_h * (out_w / ph))
                        sc_w = min(sc_w, width)

                        # X: center on subject
                        sx1 = int(tcx - sc_w / 2)
                        sx1 = max(0, min(width - sc_w, sx1))

                        # Fix #2 — Y-anchor: place face at 25% from top of panel
                        sy1 = int(tcy_raw - sc_h * 0.25)
                        sy1 = max(0, min(height - sc_h, sy1))

                        p_crop = frame[sy1 : sy1 + sc_h, sx1 : sx1 + sc_w]
                        panels.append(cv2.resize(p_crop, (out_w, ph)))

                    if len(panels) == 2:
                        # Fix #4 — 4px black separator between panels
                        separator = np.zeros((sep, out_w, 3), dtype=np.uint8)
                        output_frame = np.vstack([panels[0], separator, panels[1]])
                    elif len(panels) == 1:
                        output_frame = cv2.resize(panels[0], (out_w, out_h))
                    else:
                        # Full fallback to letterbox with BLUR background
                        output_frame = _fill_with_blur(frame, out_w, out_h)
                else:
                    # LETTERBOX: reset smooth center gradually
                    self.prev_cx = (0.05 * 0.5) + (0.95 * self.prev_cx)
                    self.prev_cy = (0.05 * 0.3) + (0.95 * self.prev_cy)
                    
                    # Fix Phase 3.2: Use Gaussian Blur Background for Letterbox
                    output_frame = _fill_with_blur(frame, out_w, out_h)

                last_frame = output_frame
            except Exception as exc:
                logger.warning(f"Frame {frame_number} processing error: {exc}")
                output_frame = last_frame if last_frame is not None else \
                    np.zeros((out_h, out_w, 3), dtype=np.uint8)

            proc.stdin.write(output_frame.tobytes())
            frame_number += 1

            if frame_number % max(1, total_frames // 10) == 0:
                pct = int(frame_number / total_frames * 100)
                logger.info(f"Render Progress: {pct}%")

        cap.release()
        proc.stdin.close()
        stderr_out = proc.stderr.read().decode()
        proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg frame render failed:\n{stderr_out[-1000:]}")

        # ── Step 5 & 6: Audio re-merge ────────────────────────────────────────
        if _has_audio(input_path):
            video_start = _get_stream_start(input_path, "v:0")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(video_start),
                 "-i", input_path, "-vn", "-acodec", "copy", tmp_aud],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["ffmpeg", "-y",
                 "-i", tmp_vid, "-i", tmp_aud,
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-shortest", output_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            for f in [tmp_vid, tmp_aud]:
                if os.path.exists(f):
                    os.remove(f)
        else:
            os.rename(tmp_vid, output_path)

        logger.info(f"✅ Render complete: {output_path}")
