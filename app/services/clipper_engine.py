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
    For each detected person, also attempts Haar Cascade face detection
    to provide a tighter, face-centered crop target.
    """
    model = _get_yolo()
    results = model([frame], classes=[0], conf=0.3, verbose=False)[0]

    detected = []
    for box in results.boxes:
        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
        person_box = [x1, y1, x2, y2]

        face_box = None
        roi = frame[y1:y2, x1:x2]
        if roi.size > 0:
            gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            faces = _get_face_cascade().detectMultiScale(
                gray_roi, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            if len(faces) > 0:
                fx, fy, fw, fh = faces[0]
                face_box = [x1 + fx, y1 + fy, x1 + fx + fw, y1 + fy + fh]

        detected.append({"person_box": person_box, "face_box": face_box})

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


def _decide_strategy(
    detections: List[Dict], frame_height: int
) -> Tuple[str, Optional[List[int]]]:
    """
    Returns ('TRACK', target_box) or ('LETTERBOX', None).
    TRACK  — crop tightly around person/face.
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
    target_cy = target_box[1] / frame_height 

    # 2. Apply EMA Smoothing
    new_cx = (alpha * target_cx) + (1 - alpha) * prev_cx
    new_cy = (alpha * target_cy) + (1 - alpha) * prev_cy

    # 3. Calculate Crop Window with Zoom
    # We crop a smaller area and then resize to target_height
    crop_h = int(frame_height / zoom_factor)
    crop_w = int(crop_h * ASPECT_RATIO)
    
    # X-axis clamping with margin enforcement
    # center of crop = new_cx * frame_width
    x1 = int(new_cx * frame_width - crop_w / 2)
    if x1 < 0: x1 = 0
    if x1 + crop_w > frame_width: x1 = frame_width - crop_w
    x2 = x1 + crop_w

    # Y-axis Framing (Face Y-Anchor at 30%)
    face_y_in_frame = new_cy * frame_height
    y1 = int(face_y_in_frame - (crop_h * 0.30))
    if y1 < 0: y1 = 0
    if y1 + crop_h > frame_height: y1 = frame_height - crop_h
    y2 = y1 + crop_h

    return x1, y1, x2, y2, new_cx, new_cy


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

    def __init__(self):
        self.smoothing_factor = 0.12
        self.prev_cx = 0.5
        self.prev_cy = 0.3
        self.hw_encoder = "h264_videotoolbox"

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

            try:
                if scene["strategy"] == "TRACK" and scene["target_box"]:
                    x1, y1, x2, y2, self.prev_cx, self.prev_cy = _calculate_crop_box(
                        scene["target_box"], width, height,
                        self.prev_cx, self.prev_cy
                    )
                    cropped = frame[y1:y2, x1:x2]
                    output_frame = cv2.resize(cropped, (out_w, out_h))
                else:
                    # LETTERBOX: reset smooth center gradually
                    self.prev_cx = (0.05 * 0.5) + (0.95 * self.prev_cx)
                    self.prev_cy = (0.05 * 0.3) + (0.95 * self.prev_cy)
                    
                    scale   = out_w / width
                    new_h   = int(height * scale)
                    scaled  = cv2.resize(frame, (out_w, new_h))
                    canvas  = np.zeros((out_h, out_w, 3), dtype=np.uint8)
                    y_off   = (out_h - new_h) // 2
                    canvas[y_off : y_off + new_h, :] = scaled
                    output_frame = canvas

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
