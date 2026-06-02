#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


# ============================================================
# DYNAMIC SPEAKER-AWARE REFRAMING - VISUAL LAYOUT ANALYZER
# VERSION: 4 ANGLE SYSTEM + SAME-SUBJECT SPLIT GUARD
# ============================================================
# Output contract:
# - layout tetap backward-compatible:
#   - "wide_context" untuk single/wide baseline
#   - "split_top_bottom" untuk split fallback renderer compatibility
#
# - layout_variant menjelaskan angle sebenarnya:
#   1. single_active_wide_lock_left
#   2. single_active_wide_lock_right
#   3. dual_active_wide_split_lr
#   4. wide_context_subject_safe
#   baseline. wide_center
#
# Rule utama:
# - Jika bingung, confidence rendah, atau tidak ada subject valid:
#   fallback ke wide_context + wide_center + pan 0.5.
# ============================================================


# ============================================================
# BASELINE / OUTPUT LAYOUT CONTRACT
# ============================================================

LAYOUT_WIDE_CONTEXT = "wide_context"

# Explicit split names. The previous code used split_top_bottom as a
# compatibility label even when the real intent was left/right split.
# That makes legacy renderers force the wrong layout for the whole clip.
LAYOUT_SPLIT_LEFT_RIGHT = "split_left_right"
LAYOUT_SPLIT_TOP_BOTTOM = "split_top_bottom"

# Keep this only as legacy/fallback metadata. New renderers should read:
# - layout
# - layout_variant
# - split_orientation
# - segments / dynamic_segments
LAYOUT_SPLIT_COMPAT = LAYOUT_SPLIT_TOP_BOTTOM

VARIANT_WIDE_CENTER = "wide_center"
VARIANT_SINGLE_LEFT = "single_active_wide_lock_left"
VARIANT_SINGLE_RIGHT = "single_active_wide_lock_right"
VARIANT_WIDE_SUBJECT_SAFE = "wide_context_subject_safe"
VARIANT_DUAL_SPLIT_LR = "dual_active_wide_split_lr"
VARIANT_DUAL_SPLIT_TB = "dual_active_wide_split_tb"

ANGLE_BASELINE = "baseline_wide_center"
ANGLE_1_LEFT = "angle_1_single_active_wide_lock_left"
ANGLE_2_RIGHT = "angle_2_single_active_wide_lock_right"
ANGLE_3_DUAL_LR = "angle_3_dual_active_wide_split_lr"
ANGLE_3_DUAL_TB = "angle_3_dual_active_wide_split_tb"
ANGLE_4_SUBJECT_SAFE = "angle_4_wide_context_subject_safe"


# ============================================================
# DETECTION CONFIG
# ============================================================

HAAR_SCALE_FACTOR = 1.06
HAAR_MIN_NEIGHBORS = 4
HAAR_MIN_SIZE = (34, 34)
HAAR_DETECTION_MAX_WIDTH = 720

MIN_FACE_AREA_RATIO = 0.00055
MAX_FACE_CENTER_Y = 0.90
MAX_FACE_TOP_Y_FOR_RELIABLE = 0.76
MAX_FACES_PER_FRAME = 8


# ============================================================
# SAMPLING CONFIG
# ============================================================

MIN_SAMPLE_COUNT = 48
MAX_SAMPLE_COUNT = 140
SAMPLES_PER_SECOND = 3.4

# ============================================================
# DYNAMIC TIMELINE / SEGMENT CONFIG
# ============================================================

# The old analyzer decided one layout for one whole highlight/clip.
# That is the root cause of split_top_bottom / split layout being applied
# from beginning to end. New flow: split each highlight into short visual
# windows, decide layout per window, smooth/merge, then output segments.
DYNAMIC_LAYOUT_ENABLED = True
DYNAMIC_SEGMENT_SECONDS = 1.60
DYNAMIC_MIN_SEGMENT_SECONDS = 0.55
DYNAMIC_SEGMENT_SAMPLES_PER_SECOND = 2.8
DYNAMIC_MIN_SAMPLE_COUNT = 4
DYNAMIC_MAX_SAMPLE_COUNT = 7

# Prevent flicker: do not let a very short isolated split/single decision
# instantly override the surrounding layout.
MIN_DYNAMIC_LAYOUT_DURATION_SECONDS = 2.20
PAN_MERGE_TOLERANCE = 0.055
PAN_SPLIT_MERGE_TOLERANCE = 0.090

# ============================================================
# VISUAL QUALITY / SHOT BOUNDARY CONFIG
# ============================================================

# These guards solve two issues seen in the rendered result:
# 1) blurred transition frames become wrong crop anchors;
# 2) scene cuts are ignored because segments were split by time only.
VISUAL_QUALITY_ENABLED = True
SHOT_BOUNDARY_ENABLED = True
SHOT_BOUNDARY_SCAN_SECONDS = 0.45
SHOT_BOUNDARY_HARD_DIFF = 0.42
SHOT_BOUNDARY_SOFT_DIFF = 0.34
SHOT_BOUNDARY_MIN_SEGMENT_SECONDS = 0.70
BLUR_BAD_SCORE = 0.24
BLUR_WEAK_SCORE = 0.36
BLUR_LAPLACIAN_LOW = 25.0
BLUR_LAPLACIAN_HIGH = 180.0
BAD_VISUAL_FACE_COUNT_MAX = 1
BAD_VISUAL_FORCE_WIDE_CENTER = True


# ============================================================
# CLUSTERING CONFIG
# ============================================================

FACE_CLUSTER_PAN_THRESHOLD = 0.22

MIN_MULTI_FACE_FRAME_RATIO_FOR_SPLIT = 0.32
MIN_SUBJECT_CO_PRESENCE_RATIO_FOR_SPLIT = 0.38


# ============================================================
# RELIABILITY CONFIG
# ============================================================

MIN_RELIABLE_SCORE = 0.36
MIN_RELIABLE_PERSISTENCE = 0.12

MIN_WEAK_FALLBACK_SCORE = 0.22
MIN_WEAK_FALLBACK_PERSISTENCE = 0.05


# ============================================================
# WIDE-CONTEXT LOCK CONFIG
# ============================================================

# Wide-center tetap baseline.
BASELINE_WIDE_CENTER_PAN = 0.5

# Untuk subject lock, tetap wide, bukan tight crop.
WIDE_LOCK_SUBJECT_WEIGHT = 0.78
EDGE_WIDE_LOCK_SUBJECT_WEIGHT = 0.92
EDGE_SUBJECT_DISTANCE_FOR_STRONG_LOCK = 0.16

# Jika subject berada di center zone, gunakan subject-safe wide.
CENTER_ZONE_MIN = 0.46
CENTER_ZONE_MAX = 0.54

LEFT_ZONE_MAX = 0.46
RIGHT_ZONE_MIN = 0.54

# A non-center angle must be supported by repeated frame-level evidence.
# This keeps the baseline safe: weak, jittery, or center-heavy subjects fall
# back to wide_center / subject_safe instead of forcing a fake angle.
MIN_ANGLE_SIDE_VOTE_RATIO = 0.58
MIN_ANGLE_CONFIDENCE = 0.48
MIN_ANGLE_FRAME_SAMPLE_COUNT = 3
MAX_ANGLE_PAN_STDEV = 0.115

# Adaptive zoom keeps the safe wide-context renderer, but enlarges the
# foreground when frame samples prove the subject will stay inside view.
ADAPTIVE_ZOOM_ENABLED = True
ADAPTIVE_ZOOM_MIN = 1.08
ADAPTIVE_ZOOM_MAX = 1.68
ADAPTIVE_ZOOM_TARGET = 1.46
ADAPTIVE_ZOOM_FACE_MARGIN_RATIO = 0.075
ADAPTIVE_ZOOM_MAX_KEYFRAME_CUT_RISK = 0.025
ADAPTIVE_ZOOM_MIN_KEYFRAME_COVERAGE = 0.975


# ============================================================
# DUAL ACTIVE LEFT-RIGHT SPLIT CONFIG
# ============================================================

LEFT_RIGHT_SPLIT_MIN_DISTANCE = 0.22
DUAL_ACTIVE_MIN_COPRESENCE = 0.34
DUAL_ACTIVE_MIN_SECOND_SCORE = 0.34
DUAL_ACTIVE_MIN_SECOND_PERSISTENCE = 0.22
DUAL_ACTIVE_MAX_GAP = 0.34
MIN_SECOND_AREA_RELATIVE_TO_TOP_FOR_DUAL = 0.42

# Split must be supported by actual same-frame co-presence, not just two
# clusters that appeared at different times in the same segment.
MIN_SPLIT_FRAME_COPRESENCE_COUNT = 2
MIN_SPLIT_FRAME_EVIDENCE_RATIO = 0.42
MAX_SPLIT_FRAME_DUPLICATE_RATIO = 0.20
TOP_BOTTOM_DUPLICATE_MAX_PAN_DISTANCE = 0.18


# ============================================================
# SAME-SUBJECT / DUPLICATE SPLIT GUARD CONFIG
# ============================================================

# Split frame hanya boleh aktif jika dua kandidat benar-benar orang/object berbeda.
# Guard ini mencegah satu orang yang sama tampil di panel atas dan bawah.
SAME_SUBJECT_IOU_THRESHOLD = 0.18
SAME_SUBJECT_MAX_PAN_DISTANCE = 0.38
SAME_SUBJECT_MAX_Y_DISTANCE = 0.12
SAME_SUBJECT_MIN_HEIGHT_RATIO = 0.55
SAME_SUBJECT_MIN_AREA_RATIO = 0.42

SAME_SUBJECT_TEMPORAL_MAX_PAN_DISTANCE = 0.30
SAME_SUBJECT_TEMPORAL_MAX_Y_DISTANCE = 0.10
SAME_SUBJECT_TEMPORAL_MIN_HEIGHT_RATIO = 0.65


# ============================================================
# FACE SAFE PAN CONFIG
# ============================================================

FACE_SAFE_ENABLED = True

# Frame-position safety is stricter than speaker pan smoothing. It validates
# the actual subject boxes sampled inside one segment before allowing a crop
# layout to stand.
FRAME_POSITION_SAFETY_ENABLED = True
FRAME_POSITION_TARGET_ASPECT = 9.0 / 16.0
FRAME_POSITION_SPLIT_PANEL_ASPECT = 1080.0 / 956.0
FRAME_POSITION_FACE_MARGIN_RATIO = 0.045
FRAME_POSITION_MAX_CUT_RISK = 0.035
FRAME_POSITION_MIN_COVERAGE = 0.965
FRAME_POSITION_LR_MIN_X_SEPARATION = 0.20
FRAME_POSITION_TB_MIN_Y_SEPARATION = 0.16
FRAME_POSITION_MAX_PANEL_CUT_RISK = 0.055
FRAME_POSITION_MAX_PANEL_OVERLAP_RATIO = 0.18
FRAME_POSITION_MAX_CROSS_PANEL_LEAK_RATIO = 0.22

SAFE_PAN_MIN = 0.04
SAFE_PAN_MAX = 0.96

FACE_CENTER_DEADZONE = 0.045
SPEAKER_LOOK_ROOM = 0.018

EDGE_FACE_BOX_MARGIN_RATIO = 0.10
EDGE_FACE_PAN_PUSH = 0.090


# ============================================================
# FADE CENTER / PAN SMOOTHING CONFIG
# ============================================================

FADE_CENTER_ENABLED = True

FACE_LOCK_HOLD_SECONDS = 1.20
CENTER_FADE_STRENGTH = 0.18
SUBJECT_LOCK_STRENGTH = 0.82

PAN_DEADZONE = 0.018
MAX_PAN_STEP_PER_CLIP = 0.085

PAN_MIN = SAFE_PAN_MIN
PAN_MAX = SAFE_PAN_MAX


# ============================================================
# BASIC HELPERS
# ============================================================

def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def safe_mean(values: List[float], default: float = 0.0) -> float:
    if not values:
        return default
    return float(sum(values) / len(values))


def parse_time_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    try:
        return float(text)
    except ValueError:
        pass

    parts = text.split(":")

    if len(parts) == 3:
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds

    if len(parts) == 2:
        minutes = float(parts[0])
        seconds = float(parts[1])
        return minutes * 60 + seconds

    raise ValueError(f"Invalid time value: {value}")


def sample_times(start: float, end: float) -> List[float]:
    duration = max(0.1, end - start)
    count = int(duration * SAMPLES_PER_SECOND)
    count = max(MIN_SAMPLE_COUNT, min(MAX_SAMPLE_COUNT, count))

    return [
        start + duration * (idx + 0.5) / count
        for idx in range(count)
    ]


def box_iou(box_a: List[int], box_b: List[int]) -> float:
    if not box_a or not box_b or len(box_a) != 4 or len(box_b) != 4:
        return 0.0

    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter_area

    if union <= 0:
        return 0.0

    return float(inter_area / union)


def ratio_similarity(first_value: float, second_value: float) -> float:
    high = max(abs(first_value), abs(second_value))
    low = min(abs(first_value), abs(second_value))

    if high <= 0:
        return 0.0

    return float(low / high)


def are_likely_same_subject(
    first: Dict[str, Any],
    second: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any]]:
    first_box = first.get("face_box") or []
    second_box = second.get("face_box") or []

    iou = box_iou(first_box, second_box)

    first_pan = float(first.get("pan", BASELINE_WIDE_CENTER_PAN))
    second_pan = float(second.get("pan", BASELINE_WIDE_CENTER_PAN))
    pan_distance = abs(first_pan - second_pan)

    first_y = float(first.get("face_center_y", 0.5))
    second_y = float(second.get("face_center_y", 0.5))
    y_distance = abs(first_y - second_y)

    first_h = float(first.get("face_height_ratio", 0.0))
    second_h = float(second.get("face_height_ratio", 0.0))
    height_similarity = ratio_similarity(first_h, second_h)

    first_area = float(first.get("median_area_ratio", 0.0))
    second_area = float(second.get("median_area_ratio", 0.0))
    area_similarity = ratio_similarity(first_area, second_area)

    first_detector = first.get("detector_type", "unknown")
    second_detector = second.get("detector_type", "unknown")

    meta = {
        "iou": round(iou, 4),
        "pan_distance": round(pan_distance, 4),
        "y_distance": round(y_distance, 4),
        "height_similarity": round(height_similarity, 4),
        "area_similarity": round(area_similarity, 4),
        "first_track_id": first.get("track_id"),
        "second_track_id": second.get("track_id"),
        "first_detector_type": first_detector,
        "second_detector_type": second_detector,
    }

    if iou >= SAME_SUBJECT_IOU_THRESHOLD:
        return True, "same_subject_iou_overlap", meta

    if (
        y_distance <= SAME_SUBJECT_MAX_Y_DISTANCE
        and height_similarity >= SAME_SUBJECT_MIN_HEIGHT_RATIO
        and area_similarity >= SAME_SUBJECT_MIN_AREA_RATIO
        and pan_distance <= SAME_SUBJECT_MAX_PAN_DISTANCE
    ):
        return True, "same_subject_similar_geometry", meta

    if (
        y_distance <= SAME_SUBJECT_TEMPORAL_MAX_Y_DISTANCE
        and height_similarity >= SAME_SUBJECT_TEMPORAL_MIN_HEIGHT_RATIO
        and pan_distance <= SAME_SUBJECT_TEMPORAL_MAX_PAN_DISTANCE
    ):
        return True, "same_subject_temporal_shift", meta

    return False, "different_subject_candidate", meta


def make_baseline_wide_center_plan(
    index: int,
    start: float,
    end: float,
    frame_width: int,
    frame_height: int,
    reason: str,
    dialog_density: float = 0.0,
) -> Dict[str, Any]:
    duration = max(0.0, end - start)

    return {
        "clip_index": index,
        "start_time": round(start, 3),
        "end_time": round(end, 3),
        "clip_start": round(start, 3),
        "clip_end": round(end, 3),
        "clip_duration": round(duration, 3),

        "layout": LAYOUT_WIDE_CONTEXT,
        "layout_variant": VARIANT_WIDE_CENTER,
        "angle": ANGLE_BASELINE,
        "layout_reason": reason,

        "pan": BASELINE_WIDE_CENTER_PAN,
        "pan_start": BASELINE_WIDE_CENTER_PAN,
        "pan_end": BASELINE_WIDE_CENTER_PAN,

        "dialog_density": round(dialog_density, 3),
        "frame_width": frame_width,
        "frame_height": frame_height,

        "subjects": [],
        "all_subjects": [],
        "active_speaker_rank": [],

        "motion": {
            "type": "locked_center",
            "duration": round(duration, 3),
            "pan_start": BASELINE_WIDE_CENTER_PAN,
            "pan_end": BASELINE_WIDE_CENTER_PAN,
        },

        "focus_safety": {
            "mode": "wide_center_baseline",
            "raw_pan": BASELINE_WIDE_CENTER_PAN,
            "face_safe_pan": BASELINE_WIDE_CENTER_PAN,
            "wide_locked_pan": BASELINE_WIDE_CENTER_PAN,
            "reason": "wide-center baseline is used when subject detection is unavailable, unstable, or ambiguous",
        },
        "frame_position": {
            "mode": "wide_center_baseline",
            "layout_candidate": LAYOUT_WIDE_CONTEXT,
            "recommended_pan": BASELINE_WIDE_CENTER_PAN,
            "safe": True,
            "coverage_ratio": 1.0,
            "cut_risk_score": 0.0,
            "validated_box_count": 0,
        },

        "split_rejection_reason": "baseline_wide_center",
        "multi_face_frame_ratio": 0.0,
        "angle_evidence": {
            "mode": "baseline",
            "angle_confidence": 0.0,
            "rejection_reason": reason,
        },

        "safety": {
            "wide_center_baseline": True,
            "center_locked": True,
            "split_frame": False,
            "subject_detection_required": False,
        },
    }


# ============================================================
# FACE DETECTION
# ============================================================

def mouth_roi(gray, x: int, y: int, w: int, h: int):
    x1 = max(0, int(x + w * 0.14))
    x2 = min(gray.shape[1], int(x + w * 0.86))
    y1 = max(0, int(y + h * 0.46))
    y2 = min(gray.shape[0], int(y + h * 0.94))

    if x2 <= x1 or y2 <= y1:
        return None

    roi = gray[y1:y2, x1:x2]

    if roi.size == 0:
        return None

    return cv2.resize(roi, (64, 36), interpolation=cv2.INTER_AREA)


def face_quality_score(
    frame_width: int,
    frame_height: int,
    x: int,
    y: int,
    w: int,
    h: int,
    detector_type: str,
) -> float:
    area_ratio = (w * h) / max(frame_width * frame_height, 1)
    face_height_ratio = h / max(frame_height, 1)
    center_y = (y + h / 2) / max(frame_height, 1)
    center_x = (x + w / 2) / max(frame_width, 1)
    aspect = w / max(h, 1)

    area_score = clamp(area_ratio / 0.018)
    height_score = clamp(face_height_ratio / 0.18)

    if detector_type in {"profile", "profile_flipped"}:
        aspect_score = clamp(1.0 - abs(aspect - 0.72) / 0.78)
        detector_bonus = 0.04
    else:
        aspect_score = clamp(1.0 - abs(aspect - 0.82) / 0.62)
        detector_bonus = 0.06

    vertical_score = clamp(1.0 - abs(center_y - 0.43) / 0.48)
    edge_score = clamp(1.0 - max(0.0, abs(center_x - 0.5) - 0.45) / 0.28)

    return clamp(
        area_score * 0.23
        + height_score * 0.22
        + aspect_score * 0.13
        + vertical_score * 0.23
        + edge_score * 0.13
        + detector_bonus
    )


def add_face_candidate(
    found: List[Dict[str, Any]],
    gray,
    frame_width: int,
    frame_height: int,
    timestamp: float,
    x: int,
    y: int,
    w: int,
    h: int,
    detector_type: str,
) -> None:
    area_ratio = (w * h) / max(frame_width * frame_height, 1)
    center_x = (x + w / 2) / max(frame_width, 1)
    center_y = (y + h / 2) / max(frame_height, 1)
    height_ratio = h / max(frame_height, 1)

    if area_ratio < MIN_FACE_AREA_RATIO:
        return

    if center_y > MAX_FACE_CENTER_Y:
        return

    quality = face_quality_score(
        frame_width=frame_width,
        frame_height=frame_height,
        x=x,
        y=y,
        w=w,
        h=h,
        detector_type=detector_type,
    )

    if quality < 0.10:
        return

    found.append(
        {
            "timestamp": round(timestamp, 3),
            "face_box": [int(x), int(y), int(x + w), int(y + h)],
            "pan": round(center_x, 4),
            "center_y": round(center_y, 4),
            "area_ratio": round(area_ratio, 5),
            "face_height_ratio": round(height_ratio, 4),
            "face_quality_score": round(quality, 3),
            "detector_type": detector_type,
            "_mouth_roi": mouth_roi(gray, x, y, w, h),
        }
    )


def deduplicate_faces(faces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not faces:
        return []

    sorted_faces = sorted(
        faces,
        key=lambda item: (
            item["face_quality_score"],
            item["area_ratio"],
        ),
        reverse=True,
    )

    kept: List[Dict[str, Any]] = []

    for face in sorted_faces:
        x1, y1, x2, y2 = face["face_box"]
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        w = x2 - x1
        h = y2 - y1

        duplicate = False

        for existing in kept:
            ex1, ey1, ex2, ey2 = existing["face_box"]
            ecx = (ex1 + ex2) / 2
            ecy = (ey1 + ey2) / 2
            ew = ex2 - ex1
            eh = ey2 - ey1

            distance = ((cx - ecx) ** 2 + (cy - ecy) ** 2) ** 0.5
            threshold = max(w, h, ew, eh) * 0.48

            if distance <= threshold:
                duplicate = True
                break

        if not duplicate:
            kept.append(face)

    return kept[:MAX_FACES_PER_FRAME]


def detect_faces_in_frame(
    frame,
    frontal_cascade: cv2.CascadeClassifier,
    profile_cascade: cv2.CascadeClassifier,
    frame_width: int,
    frame_height: int,
    timestamp: float,
) -> List[Dict[str, Any]]:
    if frame is None:
        return []

    gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Haar on full HD frames is slow. Detect on a bounded-width copy, then
    # project boxes back to original coordinates for accurate crop metadata.
    detect_scale = 1.0
    gray_detect = gray_full
    if frame_width > HAAR_DETECTION_MAX_WIDTH:
        detect_scale = HAAR_DETECTION_MAX_WIDTH / max(frame_width, 1)
        detect_height = max(1, int(frame_height * detect_scale))
        gray_detect = cv2.resize(
            gray_full,
            (HAAR_DETECTION_MAX_WIDTH, detect_height),
            interpolation=cv2.INTER_AREA,
        )

    detect_width = gray_detect.shape[1]

    def project_box(x: int, y: int, w: int, h: int) -> Tuple[int, int, int, int]:
        if detect_scale == 1.0:
            return int(x), int(y), int(w), int(h)
        inv = 1.0 / max(detect_scale, 0.001)
        return int(x * inv), int(y * inv), int(w * inv), int(h * inv)

    found: List[Dict[str, Any]] = []

    frontal_faces = frontal_cascade.detectMultiScale(
        gray_detect,
        scaleFactor=HAAR_SCALE_FACTOR,
        minNeighbors=HAAR_MIN_NEIGHBORS,
        minSize=HAAR_MIN_SIZE,
    )

    for x, y, w, h in frontal_faces:
        ox, oy, ow, oh = project_box(x, y, w, h)
        add_face_candidate(
            found=found,
            gray=gray_full,
            frame_width=frame_width,
            frame_height=frame_height,
            timestamp=timestamp,
            x=ox,
            y=oy,
            w=ow,
            h=oh,
            detector_type="frontal",
        )

    profile_faces = profile_cascade.detectMultiScale(
        gray_detect,
        scaleFactor=HAAR_SCALE_FACTOR,
        minNeighbors=max(3, HAAR_MIN_NEIGHBORS - 1),
        minSize=HAAR_MIN_SIZE,
    )

    for x, y, w, h in profile_faces:
        ox, oy, ow, oh = project_box(x, y, w, h)
        add_face_candidate(
            found=found,
            gray=gray_full,
            frame_width=frame_width,
            frame_height=frame_height,
            timestamp=timestamp,
            x=ox,
            y=oy,
            w=ow,
            h=oh,
            detector_type="profile",
        )

    flipped = cv2.flip(gray_detect, 1)
    profile_faces_flipped = profile_cascade.detectMultiScale(
        flipped,
        scaleFactor=HAAR_SCALE_FACTOR,
        minNeighbors=max(3, HAAR_MIN_NEIGHBORS - 1),
        minSize=HAAR_MIN_SIZE,
    )

    for fx, y, w, h in profile_faces_flipped:
        x = detect_width - fx - w
        ox, oy, ow, oh = project_box(x, y, w, h)
        add_face_candidate(
            found=found,
            gray=gray_full,
            frame_width=frame_width,
            frame_height=frame_height,
            timestamp=timestamp,
            x=ox,
            y=oy,
            w=ow,
            h=oh,
            detector_type="profile_flipped",
        )

    return deduplicate_faces(found)


def detect_faces_at_timestamp(
    cap: cv2.VideoCapture,
    frontal_cascade: cv2.CascadeClassifier,
    profile_cascade: cv2.CascadeClassifier,
    frame_width: int,
    frame_height: int,
    timestamp: float,
) -> List[Dict[str, Any]]:
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000)

    ok, frame = cap.read()

    if not ok or frame is None:
        return []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    found: List[Dict[str, Any]] = []

    frontal_faces = frontal_cascade.detectMultiScale(
        gray,
        scaleFactor=HAAR_SCALE_FACTOR,
        minNeighbors=HAAR_MIN_NEIGHBORS,
        minSize=HAAR_MIN_SIZE,
    )

    for x, y, w, h in frontal_faces:
        add_face_candidate(
            found=found,
            gray=gray,
            frame_width=frame_width,
            frame_height=frame_height,
            timestamp=timestamp,
            x=x,
            y=y,
            w=w,
            h=h,
            detector_type="frontal",
        )

    profile_faces = profile_cascade.detectMultiScale(
        gray,
        scaleFactor=HAAR_SCALE_FACTOR,
        minNeighbors=max(3, HAAR_MIN_NEIGHBORS - 1),
        minSize=HAAR_MIN_SIZE,
    )

    for x, y, w, h in profile_faces:
        add_face_candidate(
            found=found,
            gray=gray,
            frame_width=frame_width,
            frame_height=frame_height,
            timestamp=timestamp,
            x=x,
            y=y,
            w=w,
            h=h,
            detector_type="profile",
        )

    flipped = cv2.flip(gray, 1)

    profile_faces_flipped = profile_cascade.detectMultiScale(
        flipped,
        scaleFactor=HAAR_SCALE_FACTOR,
        minNeighbors=max(3, HAAR_MIN_NEIGHBORS - 1),
        minSize=HAAR_MIN_SIZE,
    )

    for fx, y, w, h in profile_faces_flipped:
        x = frame_width - fx - w

        add_face_candidate(
            found=found,
            gray=gray,
            frame_width=frame_width,
            frame_height=frame_height,
            timestamp=timestamp,
            x=x,
            y=y,
            w=w,
            h=h,
            detector_type="profile_flipped",
        )

    return deduplicate_faces(found)


# ============================================================
# SUBJECT CLUSTERING
# ============================================================

def merge_close_clusters(clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(clusters) <= 1:
        return clusters

    clusters = sorted(
        clusters,
        key=lambda cluster: cluster["pan_sum"] / max(cluster["count"], 1),
    )

    merged: List[Dict[str, Any]] = []

    for cluster in clusters:
        cluster_pan = cluster["pan_sum"] / max(cluster["count"], 1)

        if not merged:
            merged.append(cluster)
            continue

        previous = merged[-1]
        previous_pan = previous["pan_sum"] / max(previous["count"], 1)

        if abs(cluster_pan - previous_pan) <= FACE_CLUSTER_PAN_THRESHOLD * 0.82:
            previous["items"].extend(cluster["items"])
            previous["pan_sum"] += cluster["pan_sum"]
            previous["area_sum"] += cluster["area_sum"]
            previous["quality_sum"] += cluster["quality_sum"]
            previous["count"] += cluster["count"]
        else:
            merged.append(cluster)

    return merged


def compute_face_safe_pan(subject: Dict[str, Any], frame_width: int) -> float:
    pan = float(subject.get("pan", BASELINE_WIDE_CENTER_PAN))
    face_box = subject.get("face_box") or [0, 0, 0, 0]

    x1, _, x2, _ = face_box

    face_center_x = ((x1 + x2) / 2) / max(frame_width, 1)
    face_width_ratio = (x2 - x1) / max(frame_width, 1)

    target_pan = face_center_x

    if face_center_x < 0.5 - FACE_CENTER_DEADZONE:
        target_pan = face_center_x + SPEAKER_LOOK_ROOM
    elif face_center_x > 0.5 + FACE_CENTER_DEADZONE:
        target_pan = face_center_x - SPEAKER_LOOK_ROOM

    if x1 / max(frame_width, 1) < EDGE_FACE_BOX_MARGIN_RATIO:
        target_pan = face_center_x - EDGE_FACE_PAN_PUSH

    if x2 / max(frame_width, 1) > 1.0 - EDGE_FACE_BOX_MARGIN_RATIO:
        target_pan = face_center_x + EDGE_FACE_PAN_PUSH

    if face_width_ratio < 0.035:
        target_pan = pan

    return round(clamp(target_pan, SAFE_PAN_MIN, SAFE_PAN_MAX), 4)


def valid_box(box: Any) -> bool:
    return (
        isinstance(box, list)
        and len(box) == 4
        and float(box[2]) > float(box[0])
        and float(box[3]) > float(box[1])
    )


def box_center(box: List[int], frame_width: int, frame_height: int) -> Tuple[float, float]:
    return (
        ((float(box[0]) + float(box[2])) / 2.0) / max(frame_width, 1),
        ((float(box[1]) + float(box[3])) / 2.0) / max(frame_height, 1),
    )


def union_boxes(boxes: List[List[int]]) -> List[int]:
    clean = [box for box in boxes if valid_box(box)]
    if not clean:
        return [0, 0, 0, 0]

    return [
        int(min(box[0] for box in clean)),
        int(min(box[1] for box in clean)),
        int(max(box[2] for box in clean)),
        int(max(box[3] for box in clean)),
    ]


def percentile_box(boxes: List[List[int]], low: float = 10.0, high: float = 90.0) -> List[int]:
    clean = [box for box in boxes if valid_box(box)]
    if not clean:
        return [0, 0, 0, 0]

    values = np.array(clean, dtype=np.float32)
    return [
        int(np.percentile(values[:, 0], low)),
        int(np.percentile(values[:, 1], low)),
        int(np.percentile(values[:, 2], high)),
        int(np.percentile(values[:, 3], high)),
    ]


def compute_subject_bbox_envelope(
    items: List[Dict[str, Any]],
    frame_width: int,
    frame_height: int,
) -> Dict[str, Any]:
    boxes = [item.get("face_box") for item in items if valid_box(item.get("face_box"))]
    pans = [float(item.get("pan", BASELINE_WIDE_CENTER_PAN)) for item in items]

    if not boxes:
        return {
            "bbox_union": [0, 0, 0, 0],
            "bbox_p10_p90": [0, 0, 0, 0],
            "pan_min": BASELINE_WIDE_CENTER_PAN,
            "pan_max": BASELINE_WIDE_CENTER_PAN,
            "pan_range": 0.0,
            "edge_risk_score": 0.0,
            "sample_box_count": 0,
        }

    merged = union_boxes(boxes)
    robust = percentile_box(boxes)
    left_edge = merged[0] / max(frame_width, 1)
    right_edge = merged[2] / max(frame_width, 1)
    top_edge = merged[1] / max(frame_height, 1)
    bottom_edge = merged[3] / max(frame_height, 1)
    edge_risk = max(
        0.0,
        FRAME_POSITION_FACE_MARGIN_RATIO - left_edge,
        FRAME_POSITION_FACE_MARGIN_RATIO - top_edge,
        right_edge - (1.0 - FRAME_POSITION_FACE_MARGIN_RATIO),
        bottom_edge - (1.0 - FRAME_POSITION_FACE_MARGIN_RATIO),
    )

    pan_min = min(pans) if pans else BASELINE_WIDE_CENTER_PAN
    pan_max = max(pans) if pans else BASELINE_WIDE_CENTER_PAN

    return {
        "bbox_union": merged,
        "bbox_p10_p90": robust,
        "pan_min": round(pan_min, 4),
        "pan_max": round(pan_max, 4),
        "pan_range": round(max(0.0, pan_max - pan_min), 4),
        "edge_risk_score": round(edge_risk, 4),
        "sample_box_count": len(boxes),
    }


def cluster_faces(samples: List[Dict[str, Any]], frame_width: int, frame_height: int) -> Dict[str, Any]:
    if not samples:
        return {
            "subjects": [],
            "multi_face_frame_ratio": 0.0,
            "sample_timestamp_count": 0,
        }

    timestamp_counts: Dict[float, int] = {}

    for sample in samples:
        timestamp = sample["timestamp"]
        timestamp_counts[timestamp] = timestamp_counts.get(timestamp, 0) + 1

    sample_timestamp_count = max(1, len(timestamp_counts))
    multi_face_frame_count = sum(
        1 for count in timestamp_counts.values() if count >= 2)
    multi_face_frame_ratio = multi_face_frame_count / sample_timestamp_count

    clusters: List[Dict[str, Any]] = []

    for face in sorted(samples, key=lambda item: item["pan"]):
        match = next(
            (
                cluster
                for cluster in clusters
                if abs(cluster["pan_sum"] / max(cluster["count"], 1) - face["pan"])
                <= FACE_CLUSTER_PAN_THRESHOLD
            ),
            None,
        )

        if match is None:
            match = {
                "items": [],
                "pan_sum": 0.0,
                "area_sum": 0.0,
                "quality_sum": 0.0,
                "count": 0,
            }
            clusters.append(match)

        match["items"].append(face)
        match["pan_sum"] += face["pan"]
        match["area_sum"] += face["area_ratio"]
        match["quality_sum"] += face["face_quality_score"]
        match["count"] += 1

    clusters = merge_close_clusters(clusters)

    subjects: List[Dict[str, Any]] = []

    for idx, cluster in enumerate(clusters, start=1):
        items = cluster["items"]

        if not items:
            continue

        best = max(
            items,
            key=lambda item: (
                item["face_quality_score"],
                item["area_ratio"],
            ),
        )

        timestamps = sorted({item["timestamp"] for item in items})
        pans = [item["pan"] for item in items]
        areas = [item["area_ratio"] for item in items]
        qualities = [item["face_quality_score"] for item in items]

        persistence = min(1.0, len(timestamps) / sample_timestamp_count)
        avg_area = safe_mean(areas)
        median_area = statistics.median(areas) if areas else 0.0
        avg_quality = safe_mean(qualities)

        if len(pans) > 1:
            stability = clamp(1.0 - statistics.pstdev(pans) * 3.0)
        else:
            stability = 0.82

        co_presence_count = sum(
            1
            for timestamp in timestamps
            if timestamp_counts.get(timestamp, 0) >= 2
        )
        co_presence_ratio = co_presence_count / max(1, len(timestamps))

        roi_items = [
            item
            for item in sorted(items, key=lambda value: value["timestamp"])
            if item.get("_mouth_roi") is not None
        ]

        motion_values: List[float] = []

        for previous, current in zip(roi_items, roi_items[1:]):
            diff = cv2.absdiff(previous["_mouth_roi"], current["_mouth_roi"])
            motion_values.append(float(diff.mean()) / 255.0)

        raw_motion = safe_mean(motion_values)
        mouth_motion_score = clamp(raw_motion / 0.045)

        visibility_score = clamp(
            persistence * 0.52
            + clamp(avg_area / 0.020) * 0.27
            + avg_quality * 0.21
        )

        score = clamp(
            visibility_score * 0.74
            + stability * 0.14
            + avg_quality * 0.12
        )

        active_speaker_score = clamp(
            mouth_motion_score * 0.48
            + visibility_score * 0.25
            + stability * 0.08
            + clamp(avg_area / 0.030) * 0.08
            + avg_quality * 0.11
        )

        face_center_y = best["center_y"]
        face_height_ratio = best["face_height_ratio"]
        pan = statistics.median(pans)
        bbox_envelope = compute_subject_bbox_envelope(
            items=items,
            frame_width=frame_width,
            frame_height=frame_height,
        )

        edge_penalty = max(0.0, abs(pan - 0.5) - 0.28) / 0.34

        professional_angle_score = clamp(
            (1.0 - edge_penalty) * 0.23
            + clamp(face_height_ratio / 0.20) * 0.25
            + clamp(1.0 - abs(face_center_y - 0.43) / 0.42) * 0.21
            + stability * 0.13
            + avg_quality * 0.18
        )

        subject = {
            "track_id": f"face_{idx}",
            "pan": round(pan, 4),
            "face_safe_pan": 0.5,
            "persistence": round(persistence, 3),
            "score": round(score, 3),
            "visibility_score": round(visibility_score, 3),
            "mouth_motion_score": round(mouth_motion_score, 3),
            "active_speaker_score": round(active_speaker_score, 3),
            "professional_angle_score": round(professional_angle_score, 3),
            "face_height_ratio": round(face_height_ratio, 3),
            "face_center_y": round(face_center_y, 3),
            "raw_mouth_motion": round(raw_motion, 5),
            "avg_area_ratio": round(avg_area, 5),
            "median_area_ratio": round(median_area, 5),
            "face_quality_score": round(avg_quality, 3),
            "co_presence_ratio": round(co_presence_ratio, 3),
            "face_box": best["face_box"],
            "bbox_union": bbox_envelope["bbox_union"],
            "bbox_p10_p90": bbox_envelope["bbox_p10_p90"],
            "pan_min": bbox_envelope["pan_min"],
            "pan_max": bbox_envelope["pan_max"],
            "pan_range": bbox_envelope["pan_range"],
            "edge_risk_score": bbox_envelope["edge_risk_score"],
            "sample_box_count": bbox_envelope["sample_box_count"],
            "detector_type": best.get("detector_type", "unknown"),
            "samples": [
                {
                    key: value
                    for key, value in item.items()
                    if not key.startswith("_")
                }
                for item in items[:8]
            ],
            "timeline": [
                {
                    key: value
                    for key, value in item.items()
                    if not key.startswith("_")
                }
                for item in sorted(items, key=lambda value: value["timestamp"])
            ],
        }

        subject["face_safe_pan"] = compute_face_safe_pan(subject, frame_width)
        subjects.append(subject)

    subjects = sorted(
        subjects,
        key=lambda item: (
            item["active_speaker_score"],
            item["score"],
            item["persistence"],
        ),
        reverse=True,
    )

    if subjects:
        top_score = subjects[0]["active_speaker_score"]
        second_score = subjects[1]["active_speaker_score"] if len(
            subjects) > 1 else 0.0

        for index, subject in enumerate(subjects):
            if index == 0:
                gap = top_score - second_score
            else:
                gap = subject["active_speaker_score"] - top_score

            subject["active_speaker_confidence"] = round(clamp(gap), 3)

    return {
        "subjects": subjects,
        "multi_face_frame_ratio": round(multi_face_frame_ratio, 3),
        "sample_timestamp_count": sample_timestamp_count,
    }


# ============================================================
# LAYOUT DECISION
# ============================================================

def is_reliable_subject(subject: Dict[str, Any], frame_height: int) -> bool:
    face_box = subject.get("face_box") or [0, 0, 0, 0]
    y1 = face_box[1]

    return (
        subject["score"] >= MIN_RELIABLE_SCORE
        and subject["persistence"] >= MIN_RELIABLE_PERSISTENCE
        and y1 <= frame_height * MAX_FACE_TOP_Y_FOR_RELIABLE
    )


def is_weak_subject(subject: Dict[str, Any]) -> bool:
    return (
        subject["score"] >= MIN_WEAK_FALLBACK_SCORE
        and subject["persistence"] >= MIN_WEAK_FALLBACK_PERSISTENCE
        and subject.get("face_box") is not None
    )


def subject_side(subject: Dict[str, Any]) -> str:
    pan = float(subject.get("pan", BASELINE_WIDE_CENTER_PAN))

    if pan <= LEFT_ZONE_MAX:
        return "left"

    if pan >= RIGHT_ZONE_MIN:
        return "right"

    return "center"


def subject_frame_angle_evidence(subject: Dict[str, Any]) -> Dict[str, Any]:
    timeline = [
        item
        for item in subject.get("timeline") or subject.get("samples") or []
        if item.get("pan") is not None
    ]
    pans = [float(item.get("pan", BASELINE_WIDE_CENTER_PAN)) for item in timeline]
    sample_count = len(pans)

    if not pans:
        return {
            "sample_count": 0,
            "dominant_side": "center",
            "side_vote_ratio": 0.0,
            "left_ratio": 0.0,
            "center_ratio": 1.0,
            "right_ratio": 0.0,
            "pan_median": BASELINE_WIDE_CENTER_PAN,
            "pan_stdev": 0.0,
            "pan_stability": 1.0,
            "angle_confidence": 0.0,
            "safe_for_non_center_angle": False,
            "rejection_reason": "no_frame_angle_samples",
        }

    left_count = sum(1 for pan in pans if pan <= LEFT_ZONE_MAX)
    right_count = sum(1 for pan in pans if pan >= RIGHT_ZONE_MIN)
    center_count = sample_count - left_count - right_count
    pan_stdev = statistics.pstdev(pans) if sample_count > 1 else 0.0
    pan_stability = clamp(1.0 - pan_stdev / max(MAX_ANGLE_PAN_STDEV, 0.001))

    side_counts = {
        "left": left_count,
        "center": center_count,
        "right": right_count,
    }
    dominant_side = max(side_counts, key=lambda key: side_counts[key])
    side_vote_ratio = side_counts[dominant_side] / max(sample_count, 1)

    subject_strength = clamp(
        float(subject.get("active_speaker_score", 0.0)) * 0.40
        + float(subject.get("score", 0.0)) * 0.30
        + float(subject.get("persistence", 0.0)) * 0.20
        + float(subject.get("face_quality_score", 0.0)) * 0.10
    )
    angle_confidence = clamp(
        side_vote_ratio * 0.42
        + pan_stability * 0.25
        + subject_strength * 0.33
    )

    safe_for_non_center_angle = (
        dominant_side in {"left", "right"}
        and sample_count >= MIN_ANGLE_FRAME_SAMPLE_COUNT
        and side_vote_ratio >= MIN_ANGLE_SIDE_VOTE_RATIO
        and angle_confidence >= MIN_ANGLE_CONFIDENCE
        and pan_stdev <= MAX_ANGLE_PAN_STDEV
    )

    rejection_reason = None
    if not safe_for_non_center_angle:
        if dominant_side == "center":
            rejection_reason = "subject_votes_center"
        elif sample_count < MIN_ANGLE_FRAME_SAMPLE_COUNT:
            rejection_reason = "angle_frame_sample_count_low"
        elif side_vote_ratio < MIN_ANGLE_SIDE_VOTE_RATIO:
            rejection_reason = "side_vote_ratio_low"
        elif angle_confidence < MIN_ANGLE_CONFIDENCE:
            rejection_reason = "angle_confidence_low"
        elif pan_stdev > MAX_ANGLE_PAN_STDEV:
            rejection_reason = "pan_jitter_too_high"
        else:
            rejection_reason = "angle_evidence_ambiguous"

    return {
        "sample_count": sample_count,
        "dominant_side": dominant_side,
        "side_vote_ratio": round(side_vote_ratio, 4),
        "left_ratio": round(left_count / max(sample_count, 1), 4),
        "center_ratio": round(center_count / max(sample_count, 1), 4),
        "right_ratio": round(right_count / max(sample_count, 1), 4),
        "pan_median": round(statistics.median(pans), 4),
        "pan_stdev": round(pan_stdev, 4),
        "pan_stability": round(pan_stability, 4),
        "angle_confidence": round(angle_confidence, 4),
        "safe_for_non_center_angle": bool(safe_for_non_center_angle),
        "rejection_reason": rejection_reason,
    }


def choose_focus_pan(subject: Dict[str, Any]) -> float:
    if FACE_SAFE_ENABLED:
        return float(subject.get("face_safe_pan", subject.get("pan", BASELINE_WIDE_CENTER_PAN)))
    return float(subject.get("pan", BASELINE_WIDE_CENTER_PAN))


def compute_wide_locked_pan(subject: Dict[str, Any]) -> float:
    subject_pan = choose_focus_pan(subject)
    distance_from_center = abs(subject_pan - 0.5)

    if distance_from_center >= EDGE_SUBJECT_DISTANCE_FOR_STRONG_LOCK:
        weight = EDGE_WIDE_LOCK_SUBJECT_WEIGHT
    else:
        weight = WIDE_LOCK_SUBJECT_WEIGHT

    pan = subject_pan * weight + BASELINE_WIDE_CENTER_PAN * (1.0 - weight)

    return round(clamp(pan, SAFE_PAN_MIN, SAFE_PAN_MAX), 4)


def compute_dialog_density(text: str) -> float:
    lower = text.lower()

    return clamp(
        text.count("?") * 0.12
        + lower.count("tapi") * 0.06
        + lower.count("bukan") * 0.06
        + lower.count("kenapa") * 0.06
        + lower.count("gimana") * 0.06
    )


def is_dual_active_left_right_valid(
    top: Dict[str, Any],
    second: Dict[str, Any],
    multi_face_frame_ratio: float,
) -> Tuple[bool, str]:
    same_subject, same_subject_reason, same_subject_meta = are_likely_same_subject(
        top, second)

    top["same_subject_guard"] = same_subject_meta
    second["same_subject_guard"] = same_subject_meta

    if same_subject:
        return False, f"reject_dual_split_same_subject_{same_subject_reason}"

    if multi_face_frame_ratio < MIN_MULTI_FACE_FRAME_RATIO_FOR_SPLIT:
        return False, "reject_dual_split_multi_face_frame_ratio_low"

    top_side = subject_side(top)
    second_side = subject_side(second)

    if {top_side, second_side} != {"left", "right"}:
        return False, "reject_dual_split_not_left_right_subjects"

    pan_distance = abs(float(top["pan"]) - float(second["pan"]))

    if pan_distance < LEFT_RIGHT_SPLIT_MIN_DISTANCE:
        return False, "reject_dual_split_pan_distance_too_close"

    if multi_face_frame_ratio < DUAL_ACTIVE_MIN_COPRESENCE:
        return False, "reject_dual_split_not_copresent_enough"

    if top.get("co_presence_ratio", 0.0) < MIN_SUBJECT_CO_PRESENCE_RATIO_FOR_SPLIT:
        return False, "reject_dual_split_top_not_copresent"

    if second.get("co_presence_ratio", 0.0) < MIN_SUBJECT_CO_PRESENCE_RATIO_FOR_SPLIT:
        return False, "reject_dual_split_second_not_copresent"

    if second["score"] < DUAL_ACTIVE_MIN_SECOND_SCORE:
        return False, "reject_dual_split_second_score_low"

    if second["persistence"] < DUAL_ACTIVE_MIN_SECOND_PERSISTENCE:
        return False, "reject_dual_split_second_persistence_low"

    active_gap = abs(top["active_speaker_score"] -
                     second["active_speaker_score"])

    if active_gap > DUAL_ACTIVE_MAX_GAP:
        return False, "reject_dual_split_one_speaker_too_dominant"

    top_area = max(top.get("median_area_ratio", 0.0), 0.00001)
    second_area = second.get("median_area_ratio", 0.0)
    area_relative = second_area / top_area

    if area_relative < MIN_SECOND_AREA_RELATIVE_TO_TOP_FOR_DUAL:
        return False, "reject_dual_split_second_subject_too_small"

    return True, "valid_dual_active_left_right"


def is_dual_active_pair_valid(
    top: Dict[str, Any],
    second: Dict[str, Any],
    multi_face_frame_ratio: float,
    *,
    orientation: str,
    frame_width: int,
    frame_height: int,
) -> Tuple[bool, str]:
    if orientation == "left_right":
        return is_dual_active_left_right_valid(top, second, multi_face_frame_ratio)

    same_subject, same_subject_reason, same_subject_meta = are_likely_same_subject(
        top, second)
    top["same_subject_guard"] = same_subject_meta
    second["same_subject_guard"] = same_subject_meta

    if same_subject:
        return False, f"reject_dual_split_same_subject_{same_subject_reason}"

    if multi_face_frame_ratio < MIN_MULTI_FACE_FRAME_RATIO_FOR_SPLIT:
        return False, "reject_dual_split_multi_face_frame_ratio_low"

    top_box = subject_safety_box(top)
    second_box = subject_safety_box(second)
    _, top_y = box_center(top_box, frame_width, frame_height)
    _, second_y = box_center(second_box, frame_width, frame_height)

    if abs(top_y - second_y) < FRAME_POSITION_TB_MIN_Y_SEPARATION:
        return False, "reject_dual_split_vertical_distance_too_close"

    if multi_face_frame_ratio < DUAL_ACTIVE_MIN_COPRESENCE:
        return False, "reject_dual_split_not_copresent_enough"

    if top.get("co_presence_ratio", 0.0) < MIN_SUBJECT_CO_PRESENCE_RATIO_FOR_SPLIT:
        return False, "reject_dual_split_top_not_copresent"

    if second.get("co_presence_ratio", 0.0) < MIN_SUBJECT_CO_PRESENCE_RATIO_FOR_SPLIT:
        return False, "reject_dual_split_second_not_copresent"

    if second["score"] < DUAL_ACTIVE_MIN_SECOND_SCORE:
        return False, "reject_dual_split_second_score_low"

    if second["persistence"] < DUAL_ACTIVE_MIN_SECOND_PERSISTENCE:
        return False, "reject_dual_split_second_persistence_low"

    active_gap = abs(top["active_speaker_score"] - second["active_speaker_score"])

    if active_gap > DUAL_ACTIVE_MAX_GAP:
        return False, "reject_dual_split_one_speaker_too_dominant"

    top_area = max(top.get("median_area_ratio", 0.0), 0.00001)
    second_area = second.get("median_area_ratio", 0.0)
    if second_area / top_area < MIN_SECOND_AREA_RELATIVE_TO_TOP_FOR_DUAL:
        return False, "reject_dual_split_second_subject_too_small"

    return True, "valid_dual_active_top_bottom"


def subject_safety_box(subject: Dict[str, Any]) -> List[int]:
    for key in ("bbox_union", "bbox_p10_p90", "face_box"):
        box = subject.get(key)
        if valid_box(box):
            return [int(value) for value in box]
    return [0, 0, 0, 0]


def crop_width_ratio_for_aspect(frame_width: int, frame_height: int, aspect: float) -> float:
    crop_width = min(float(frame_width), float(frame_height) * aspect)
    return clamp(crop_width / max(frame_width, 1), 0.001, 1.0)


def compute_safe_pan_for_boxes(
    boxes: List[List[int]],
    *,
    frame_width: int,
    frame_height: int,
    aspect: float,
    preferred_pan: float,
) -> Tuple[float, Dict[str, Any]]:
    clean = [box for box in boxes if valid_box(box)]
    crop_ratio = crop_width_ratio_for_aspect(frame_width, frame_height, aspect)
    crop_half = crop_ratio / 2.0
    min_pan = crop_half
    max_pan = 1.0 - crop_half

    if not clean:
        pan = clamp(preferred_pan, min_pan, max_pan)
        return round(pan, 4), {
            "safe": True,
            "coverage_ratio": 1.0,
            "cut_risk_score": 0.0,
            "crop_width_ratio": round(crop_ratio, 4),
            "crop_box": [
                round(clamp(pan - crop_half), 4),
                0.0,
                round(clamp(pan + crop_half), 4),
                1.0,
            ],
            "validated_box_count": 0,
        }

    union = union_boxes(clean)
    margin_x = FRAME_POSITION_FACE_MARGIN_RATIO * frame_width
    x1 = max(0.0, float(union[0]) - margin_x)
    x2 = min(float(frame_width), float(union[2]) + margin_x)
    preferred = clamp(preferred_pan, min_pan, max_pan)

    lower = (x2 / max(frame_width, 1)) - crop_half
    upper = (x1 / max(frame_width, 1)) + crop_half
    feasible_low = max(min_pan, lower)
    feasible_high = min(max_pan, upper)

    if feasible_low <= feasible_high:
        pan = clamp(preferred, feasible_low, feasible_high)
    else:
        center = ((x1 + x2) / 2.0) / max(frame_width, 1)
        pan = clamp(center, min_pan, max_pan)

    crop_left = max(0.0, min(1.0 - crop_ratio, pan - crop_half))
    crop_right = crop_left + crop_ratio
    crop_left_px = crop_left * frame_width
    crop_right_px = crop_right * frame_width

    required_width = max(1.0, x2 - x1)
    overflow_left = max(0.0, crop_left_px - x1)
    overflow_right = max(0.0, x2 - crop_right_px)
    cut_risk = (overflow_left + overflow_right) / required_width
    coverage = clamp(1.0 - cut_risk)

    return round(clamp(pan, min_pan, max_pan), 4), {
        "safe": bool(cut_risk <= FRAME_POSITION_MAX_CUT_RISK and coverage >= FRAME_POSITION_MIN_COVERAGE),
        "coverage_ratio": round(coverage, 4),
        "cut_risk_score": round(cut_risk, 4),
        "crop_width_ratio": round(crop_ratio, 4),
        "crop_box": [
            round(crop_left, 4),
            0.0,
            round(crop_right, 4),
            1.0,
        ],
        "subject_union_box": union,
        "validated_box_count": len(clean),
        "feasible_pan_interval": [
            round(feasible_low, 4),
            round(feasible_high, 4),
        ],
    }


def compute_safe_pan_for_crop_ratio(
    boxes: List[List[int]],
    *,
    frame_width: int,
    preferred_pan: float,
    crop_width_ratio: float,
    margin_ratio: float,
) -> Tuple[float, Dict[str, Any]]:
    clean = [box for box in boxes if valid_box(box)]
    crop_ratio = clamp(crop_width_ratio, 0.001, 1.0)
    crop_half = crop_ratio / 2.0
    min_pan = crop_half
    max_pan = 1.0 - crop_half

    if not clean:
        pan = clamp(preferred_pan, min_pan, max_pan)
        return round(pan, 4), {
            "safe": True,
            "coverage_ratio": 1.0,
            "cut_risk_score": 0.0,
            "crop_width_ratio": round(crop_ratio, 4),
            "crop_box": [
                round(clamp(pan - crop_half), 4),
                0.0,
                round(clamp(pan + crop_half), 4),
                1.0,
            ],
            "validated_box_count": 0,
        }

    union = union_boxes(clean)
    margin_x = margin_ratio * frame_width
    x1 = max(0.0, float(union[0]) - margin_x)
    x2 = min(float(frame_width), float(union[2]) + margin_x)
    preferred = clamp(preferred_pan, min_pan, max_pan)

    lower = (x2 / max(frame_width, 1)) - crop_half
    upper = (x1 / max(frame_width, 1)) + crop_half
    feasible_low = max(min_pan, lower)
    feasible_high = min(max_pan, upper)

    if feasible_low <= feasible_high:
        pan = clamp(preferred, feasible_low, feasible_high)
    else:
        center = ((x1 + x2) / 2.0) / max(frame_width, 1)
        pan = clamp(center, min_pan, max_pan)

    crop_left = max(0.0, min(1.0 - crop_ratio, pan - crop_half))
    crop_right = crop_left + crop_ratio
    crop_left_px = crop_left * frame_width
    crop_right_px = crop_right * frame_width

    required_width = max(1.0, x2 - x1)
    overflow_left = max(0.0, crop_left_px - x1)
    overflow_right = max(0.0, x2 - crop_right_px)
    cut_risk = (overflow_left + overflow_right) / required_width
    coverage = clamp(1.0 - cut_risk)

    return round(clamp(pan, min_pan, max_pan), 4), {
        "safe": bool(
            cut_risk <= ADAPTIVE_ZOOM_MAX_KEYFRAME_CUT_RISK
            and coverage >= ADAPTIVE_ZOOM_MIN_KEYFRAME_COVERAGE
        ),
        "coverage_ratio": round(coverage, 4),
        "cut_risk_score": round(cut_risk, 4),
        "crop_width_ratio": round(crop_ratio, 4),
        "crop_box": [
            round(crop_left, 4),
            0.0,
            round(crop_right, 4),
            1.0,
        ],
        "subject_union_box": union,
        "validated_box_count": len(clean),
        "feasible_pan_interval": [
            round(feasible_low, 4),
            round(feasible_high, 4),
        ],
    }


def required_crop_ratio_for_boxes(
    boxes: List[List[int]],
    *,
    frame_width: int,
    margin_ratio: float,
) -> float:
    clean = [box for box in boxes if valid_box(box)]
    if not clean:
        return 1.0
    union = union_boxes(clean)
    margin_x = margin_ratio * frame_width
    x1 = max(0.0, float(union[0]) - margin_x)
    x2 = min(float(frame_width), float(union[2]) + margin_x)
    return clamp((x2 - x1) / max(frame_width, 1), 0.001, 1.0)


def build_adaptive_zoom_keyframes(
    subject: Dict[str, Any],
    *,
    frame_width: int,
    crop_width_ratio: float,
) -> List[Dict[str, Any]]:
    keyframes: List[Dict[str, Any]] = []
    for item in subject.get("timeline") or subject.get("samples") or []:
        box = item.get("face_box")
        if not valid_box(box):
            continue
        preferred_pan = float(item.get("pan", subject.get("face_safe_pan", subject.get("pan", BASELINE_WIDE_CENTER_PAN))))
        pan, safety = compute_safe_pan_for_crop_ratio(
            [[int(value) for value in box]],
            frame_width=frame_width,
            preferred_pan=preferred_pan,
            crop_width_ratio=crop_width_ratio,
            margin_ratio=ADAPTIVE_ZOOM_FACE_MARGIN_RATIO,
        )
        keyframes.append(
            {
                "timestamp": item.get("timestamp"),
                "track_id": subject.get("track_id"),
                "pan": pan,
                "safe": safety["safe"],
                "coverage_ratio": safety["coverage_ratio"],
                "cut_risk_score": safety["cut_risk_score"],
                "crop_box": safety["crop_box"],
            }
        )
    return keyframes[:12]


def evaluate_adaptive_zoom_frame_position(
    subject: Dict[str, Any],
    *,
    frame_width: int,
    frame_height: int,
    preferred_pan: float,
) -> Dict[str, Any]:
    boxes = [
        item.get("face_box")
        for item in subject.get("timeline") or subject.get("samples") or []
        if valid_box(item.get("face_box"))
    ]
    if not boxes:
        boxes = [subject_safety_box(subject)]

    required_ratio = required_crop_ratio_for_boxes(
        boxes,
        frame_width=frame_width,
        margin_ratio=ADAPTIVE_ZOOM_FACE_MARGIN_RATIO,
    )
    max_safe_zoom = 1.0 / max(required_ratio, 0.001)
    max_vertical_safe_zoom = (1920.0 * max(frame_width, 1)) / (1080.0 * max(frame_height, 1))
    zoom = min(ADAPTIVE_ZOOM_TARGET, ADAPTIVE_ZOOM_MAX, max_safe_zoom, max_vertical_safe_zoom)

    if zoom < ADAPTIVE_ZOOM_MIN:
        return {
            "mode": "adaptive_zoom_blur",
            "render_mode": "wide_fit_blur",
            "adaptive_zoom_enabled": False,
            "adaptive_zoom_rejection_reason": (
                "vertical_zoom_limit_too_low"
                if max_vertical_safe_zoom < ADAPTIVE_ZOOM_MIN
                else "required_subject_width_too_large"
            ),
            "zoom": 1.0,
            "crop_width_ratio": 1.0,
            "recommended_pan": BASELINE_WIDE_CENTER_PAN,
            "safe": False,
            "coverage_ratio": 1.0,
            "cut_risk_score": 0.0,
            "validated_box_count": len(boxes),
        }

    crop_ratio = clamp(1.0 / zoom, 0.001, 1.0)
    pan, safety = compute_safe_pan_for_crop_ratio(
        boxes,
        frame_width=frame_width,
        preferred_pan=preferred_pan,
        crop_width_ratio=crop_ratio,
        margin_ratio=ADAPTIVE_ZOOM_FACE_MARGIN_RATIO,
    )
    keyframes = build_adaptive_zoom_keyframes(
        subject,
        frame_width=frame_width,
        crop_width_ratio=crop_ratio,
    )
    if keyframes:
        keyframe_safe_ratio = sum(1 for item in keyframes if item.get("safe")) / len(keyframes)
        max_keyframe_cut_risk = max(float(item.get("cut_risk_score", 0.0)) for item in keyframes)
    else:
        keyframe_safe_ratio = 0.0
        max_keyframe_cut_risk = 1.0

    safe = (
        bool(safety.get("safe"))
        and keyframe_safe_ratio >= ADAPTIVE_ZOOM_MIN_KEYFRAME_COVERAGE
        and max_keyframe_cut_risk <= ADAPTIVE_ZOOM_MAX_KEYFRAME_CUT_RISK
    )

    return {
        "mode": "adaptive_zoom_blur",
        "layout_candidate": LAYOUT_WIDE_CONTEXT,
        "render_mode": "adaptive_zoom_blur" if safe else "wide_fit_blur",
        "adaptive_zoom_enabled": bool(safe),
        "adaptive_zoom_rejection_reason": None if safe else "adaptive_zoom_keyframe_unsafe",
        "zoom": round(zoom if safe else 1.0, 4),
        "crop_width_ratio": round(crop_ratio if safe else 1.0, 4),
        "recommended_pan": pan if safe else BASELINE_WIDE_CENTER_PAN,
        "safe": bool(safe),
        "coverage_ratio": safety.get("coverage_ratio", 1.0),
        "cut_risk_score": safety.get("cut_risk_score", 0.0),
        "crop_box": safety.get("crop_box", [0.0, 0.0, 1.0, 1.0]),
        "required_crop_width_ratio": round(required_ratio, 4),
        "max_safe_zoom": round(max_safe_zoom, 4),
        "max_vertical_safe_zoom": round(max_vertical_safe_zoom, 4),
        "keyframe_safe_ratio": round(keyframe_safe_ratio, 4),
        "max_keyframe_cut_risk": round(max_keyframe_cut_risk, 4),
        "validated_box_count": len(boxes),
        "keyframes": keyframes,
    }


def interval_overlap_ratio(
    first_left: float,
    first_right: float,
    second_left: float,
    second_right: float,
) -> float:
    overlap = max(0.0, min(first_right, second_right) - max(first_left, second_left))
    base = max(0.001, min(first_right - first_left, second_right - second_left))
    return clamp(overlap / base)


def box_horizontal_coverage_in_crop(
    box: List[int],
    crop_box: List[float],
    frame_width: int,
) -> float:
    if not valid_box(box) or not crop_box or len(crop_box) < 4:
        return 0.0

    box_left = float(box[0]) / max(frame_width, 1)
    box_right = float(box[2]) / max(frame_width, 1)
    crop_left = float(crop_box[0])
    crop_right = float(crop_box[2])
    overlap = max(0.0, min(box_right, crop_right) - max(box_left, crop_left))
    return clamp(overlap / max(0.001, box_right - box_left))


def evaluate_cross_panel_leak(
    subjects: List[Dict[str, Any]],
    panels: List[Dict[str, Any]],
    frame_width: int,
) -> Dict[str, Any]:
    if len(subjects) < 2 or len(panels) < 2:
        return {
            "panel_crop_overlap_ratio": 0.0,
            "cross_panel_subject_leak": [],
            "max_cross_panel_leak_ratio": 0.0,
            "safe": True,
        }

    panel_a = panels[0]
    panel_b = panels[1]
    crop_a = panel_a.get("crop_box") or []
    crop_b = panel_b.get("crop_box") or []
    panel_overlap = interval_overlap_ratio(
        float(crop_a[0]),
        float(crop_a[2]),
        float(crop_b[0]),
        float(crop_b[2]),
    )

    leaks: List[Dict[str, Any]] = []
    max_leak = 0.0

    for subject, own_panel, other_panel in [
        (subjects[0], panel_a, panel_b),
        (subjects[1], panel_b, panel_a),
    ]:
        box = subject_safety_box(subject)
        leak_ratio = box_horizontal_coverage_in_crop(
            box,
            other_panel.get("crop_box") or [],
            frame_width,
        )
        max_leak = max(max_leak, leak_ratio)
        leaks.append(
            {
                "track_id": subject.get("track_id"),
                "own_panel": own_panel.get("panel"),
                "leaks_into_panel": other_panel.get("panel"),
                "leak_ratio": round(leak_ratio, 4),
                "subject_box": box,
            }
        )

    safe = (
        panel_overlap <= FRAME_POSITION_MAX_PANEL_OVERLAP_RATIO
        and max_leak <= FRAME_POSITION_MAX_CROSS_PANEL_LEAK_RATIO
    )

    return {
        "panel_crop_overlap_ratio": round(panel_overlap, 4),
        "cross_panel_subject_leak": leaks,
        "max_cross_panel_leak_ratio": round(max_leak, 4),
        "safe": bool(safe),
    }


def build_single_position_keyframes(
    subject: Dict[str, Any],
    *,
    frame_width: int,
    frame_height: int,
    aspect: float,
) -> List[Dict[str, Any]]:
    keyframes: List[Dict[str, Any]] = []
    for item in subject.get("timeline") or subject.get("samples") or []:
        box = item.get("face_box")
        if not valid_box(box):
            continue

        preferred_pan = float(item.get("pan", subject.get("face_safe_pan", subject.get("pan", BASELINE_WIDE_CENTER_PAN))))
        pan, safety = compute_safe_pan_for_boxes(
            [[int(value) for value in box]],
            frame_width=frame_width,
            frame_height=frame_height,
            aspect=aspect,
            preferred_pan=preferred_pan,
        )
        keyframes.append(
            {
                "timestamp": item.get("timestamp"),
                "track_id": subject.get("track_id"),
                "pan": pan,
                "safe": safety["safe"],
                "coverage_ratio": safety["coverage_ratio"],
                "cut_risk_score": safety["cut_risk_score"],
                "crop_box": safety["crop_box"],
            }
        )

    return keyframes[:12]


def evaluate_single_frame_position(
    subject: Dict[str, Any],
    *,
    frame_width: int,
    frame_height: int,
    preferred_pan: float,
) -> Dict[str, Any]:
    pan, safety = compute_safe_pan_for_boxes(
        [subject_safety_box(subject)],
        frame_width=frame_width,
        frame_height=frame_height,
        aspect=FRAME_POSITION_TARGET_ASPECT,
        preferred_pan=preferred_pan,
    )
    return {
        "mode": "adaptive_single_safe_crop",
        "layout_candidate": LAYOUT_WIDE_CONTEXT,
        "recommended_pan": pan,
        "safe": safety["safe"],
        "keyframes": build_single_position_keyframes(
            subject,
            frame_width=frame_width,
            frame_height=frame_height,
            aspect=FRAME_POSITION_TARGET_ASPECT,
        ),
        **safety,
    }


def evaluate_wide_context_frame_position(
    subject: Optional[Dict[str, Any]],
    *,
    frame_width: int,
    frame_height: int,
    preferred_pan: float = BASELINE_WIDE_CENTER_PAN,
) -> Dict[str, Any]:
    """Wide-context renderer fits the full landscape frame over a blurred BG."""
    if subject:
        tight_pan, tight_safety = compute_safe_pan_for_boxes(
            [subject_safety_box(subject)],
            frame_width=frame_width,
            frame_height=frame_height,
            aspect=FRAME_POSITION_TARGET_ASPECT,
            preferred_pan=preferred_pan,
        )
        keyframes = build_single_position_keyframes(
            subject,
            frame_width=frame_width,
            frame_height=frame_height,
            aspect=FRAME_POSITION_TARGET_ASPECT,
        )
    else:
        tight_pan = BASELINE_WIDE_CENTER_PAN
        tight_safety = {
            "safe": True,
            "coverage_ratio": 1.0,
            "cut_risk_score": 0.0,
            "crop_box": [0.0, 0.0, 1.0, 1.0],
            "validated_box_count": 0,
        }
        keyframes = []

    return {
        "mode": "wide_fit_blur_subject_safe",
        "layout_candidate": LAYOUT_WIDE_CONTEXT,
        "render_mode": "wide_fit_blur",
        "recommended_pan": BASELINE_WIDE_CENTER_PAN,
        "safe": True,
        "coverage_ratio": 1.0,
        "cut_risk_score": 0.0,
        "crop_box": [0.0, 0.0, 1.0, 1.0],
        "validated_box_count": tight_safety.get("validated_box_count", 0),
        "crop_risk_if_tight": {
            "recommended_pan": tight_pan,
            "safe": tight_safety.get("safe", True),
            "coverage_ratio": tight_safety.get("coverage_ratio", 1.0),
            "cut_risk_score": tight_safety.get("cut_risk_score", 0.0),
            "crop_box": tight_safety.get("crop_box"),
        },
        "keyframes": keyframes,
    }


def split_orientation_from_subjects(
    first: Dict[str, Any],
    second: Dict[str, Any],
    frame_width: int,
    frame_height: int,
) -> str:
    first_box = subject_safety_box(first)
    second_box = subject_safety_box(second)
    first_x, first_y = box_center(first_box, frame_width, frame_height)
    second_x, second_y = box_center(second_box, frame_width, frame_height)

    x_distance = abs(first_x - second_x)
    y_distance = abs(first_y - second_y)

    if y_distance >= FRAME_POSITION_TB_MIN_Y_SEPARATION and y_distance > x_distance * 0.80:
        return "top_bottom"

    return "left_right"


def timeline_by_timestamp(subject: Dict[str, Any]) -> Dict[float, Dict[str, Any]]:
    frames: Dict[float, Dict[str, Any]] = {}
    for item in subject.get("timeline") or subject.get("samples") or []:
        if not valid_box(item.get("face_box")):
            continue
        try:
            timestamp = round(float(item.get("timestamp")), 3)
        except Exception:
            continue
        frames[timestamp] = item
    return frames


def validate_split_frame_evidence(
    first: Dict[str, Any],
    second: Dict[str, Any],
    *,
    orientation: str,
    frame_width: int,
    frame_height: int,
) -> Dict[str, Any]:
    first_frames = timeline_by_timestamp(first)
    second_frames = timeline_by_timestamp(second)
    common_times = sorted(set(first_frames).intersection(second_frames))
    possible_times = max(len(set(first_frames).union(second_frames)), 1)

    x_distances: List[float] = []
    y_distances: List[float] = []
    duplicate_like_count = 0

    for timestamp in common_times:
        first_box = [int(value) for value in first_frames[timestamp]["face_box"]]
        second_box = [int(value) for value in second_frames[timestamp]["face_box"]]
        first_x, first_y = box_center(first_box, frame_width, frame_height)
        second_x, second_y = box_center(second_box, frame_width, frame_height)
        x_distance = abs(first_x - second_x)
        y_distance = abs(first_y - second_y)
        x_distances.append(x_distance)
        y_distances.append(y_distance)

        first_height = (first_box[3] - first_box[1]) / max(frame_height, 1)
        second_height = (second_box[3] - second_box[1]) / max(frame_height, 1)
        height_similarity = ratio_similarity(first_height, second_height)
        pan_distance = abs(
            float(first_frames[timestamp].get("pan", first_x))
            - float(second_frames[timestamp].get("pan", second_x))
        )
        same_box = box_iou(first_box, second_box) >= SAME_SUBJECT_IOU_THRESHOLD
        same_vertical_duplicate = (
            orientation == "top_bottom"
            and pan_distance <= TOP_BOTTOM_DUPLICATE_MAX_PAN_DISTANCE
            and height_similarity >= SAME_SUBJECT_TEMPORAL_MIN_HEIGHT_RATIO
        )
        same_horizontal_duplicate = (
            orientation == "left_right"
            and y_distance <= SAME_SUBJECT_TEMPORAL_MAX_Y_DISTANCE
            and height_similarity >= SAME_SUBJECT_TEMPORAL_MIN_HEIGHT_RATIO
            and pan_distance <= SAME_SUBJECT_TEMPORAL_MAX_PAN_DISTANCE
        )
        if same_box or same_vertical_duplicate or same_horizontal_duplicate:
            duplicate_like_count += 1

    copresence_count = len(common_times)
    evidence_ratio = copresence_count / possible_times
    median_x_distance = statistics.median(x_distances) if x_distances else 0.0
    median_y_distance = statistics.median(y_distances) if y_distances else 0.0
    duplicate_ratio = duplicate_like_count / max(copresence_count, 1)

    enough_copresence = (
        copresence_count >= MIN_SPLIT_FRAME_COPRESENCE_COUNT
        and evidence_ratio >= MIN_SPLIT_FRAME_EVIDENCE_RATIO
    )
    enough_separation = (
        median_y_distance >= FRAME_POSITION_TB_MIN_Y_SEPARATION
        if orientation == "top_bottom"
        else median_x_distance >= FRAME_POSITION_LR_MIN_X_SEPARATION
    )
    duplicate_safe = duplicate_ratio <= MAX_SPLIT_FRAME_DUPLICATE_RATIO
    safe = enough_copresence and enough_separation and duplicate_safe

    if safe:
        rejection_reason = None
    elif not enough_copresence:
        rejection_reason = "reject_split_frame_copresence_low"
    elif not enough_separation:
        rejection_reason = (
            "reject_split_frame_vertical_separation_low"
            if orientation == "top_bottom"
            else "reject_split_frame_horizontal_separation_low"
        )
    elif not duplicate_safe:
        rejection_reason = "reject_split_duplicate_subject_frame_evidence"
    else:
        rejection_reason = "reject_split_frame_evidence_ambiguous"

    return {
        "safe": bool(safe),
        "orientation": orientation,
        "copresence_count": copresence_count,
        "possible_timestamp_count": possible_times,
        "evidence_ratio": round(evidence_ratio, 4),
        "median_x_distance": round(median_x_distance, 4),
        "median_y_distance": round(median_y_distance, 4),
        "duplicate_like_count": duplicate_like_count,
        "duplicate_like_ratio": round(duplicate_ratio, 4),
        "rejection_reason": rejection_reason,
    }


def evaluate_split_frame_position(
    subjects: List[Dict[str, Any]],
    *,
    frame_width: int,
    frame_height: int,
    orientation: str,
) -> Dict[str, Any]:
    ordered = sorted(
        subjects,
        key=(
            (lambda item: box_center(subject_safety_box(item), frame_width, frame_height)[1])
            if orientation == "top_bottom"
            else (lambda item: float(item.get("pan", BASELINE_WIDE_CENTER_PAN)))
        ),
    )[:2]

    panels: List[Dict[str, Any]] = []
    cut_risks: List[float] = []
    coverages: List[float] = []
    keyframe_safe_ratios: List[float] = []
    keyframe_cut_risks: List[float] = []

    for index, subject in enumerate(ordered):
        preferred_pan = float(subject.get("face_safe_pan", subject.get("pan", BASELINE_WIDE_CENTER_PAN)))
        pan, safety = compute_safe_pan_for_boxes(
            [subject_safety_box(subject)],
            frame_width=frame_width,
            frame_height=frame_height,
            aspect=FRAME_POSITION_SPLIT_PANEL_ASPECT,
            preferred_pan=preferred_pan,
        )
        panel_name = ("top" if index == 0 else "bottom") if orientation == "top_bottom" else ("left" if index == 0 else "right")
        keyframes = build_single_position_keyframes(
            subject,
            frame_width=frame_width,
            frame_height=frame_height,
            aspect=FRAME_POSITION_SPLIT_PANEL_ASPECT,
        )
        if keyframes:
            keyframe_safe_ratio = sum(1 for item in keyframes if item.get("safe")) / len(keyframes)
            max_keyframe_cut_risk = max(
                float(item.get("cut_risk_score", 0.0))
                for item in keyframes
            )
        else:
            keyframe_safe_ratio = 0.0
            max_keyframe_cut_risk = 1.0
        panels.append(
            {
                "panel": panel_name,
                "track_id": subject.get("track_id"),
                "pan": pan,
                "safe": safety["safe"],
                "coverage_ratio": safety["coverage_ratio"],
                "cut_risk_score": safety["cut_risk_score"],
                "crop_box": safety["crop_box"],
                "keyframe_safe_ratio": round(keyframe_safe_ratio, 4),
                "max_keyframe_cut_risk": round(max_keyframe_cut_risk, 4),
                "keyframes": keyframes,
            }
        )
        cut_risks.append(float(safety["cut_risk_score"]))
        coverages.append(float(safety["coverage_ratio"]))
        keyframe_safe_ratios.append(keyframe_safe_ratio)
        keyframe_cut_risks.append(max_keyframe_cut_risk)

    max_cut_risk = max(cut_risks, default=0.0)
    min_coverage = min(coverages, default=1.0)
    min_keyframe_safe_ratio = min(keyframe_safe_ratios, default=0.0)
    max_keyframe_cut_risk = max(keyframe_cut_risks, default=1.0)
    leak_guard = evaluate_cross_panel_leak(
        ordered,
        panels,
        frame_width,
    )
    safe = (
        len(ordered) >= 2
        and max_cut_risk <= FRAME_POSITION_MAX_PANEL_CUT_RISK
        and min_coverage >= FRAME_POSITION_MIN_COVERAGE
        and min_keyframe_safe_ratio >= FRAME_POSITION_MIN_COVERAGE
        and max_keyframe_cut_risk <= FRAME_POSITION_MAX_PANEL_CUT_RISK
        and leak_guard.get("safe", True)
    )

    return {
        "mode": "adaptive_split_safe_panels",
        "layout_candidate": LAYOUT_SPLIT_TOP_BOTTOM if orientation == "top_bottom" else LAYOUT_SPLIT_LEFT_RIGHT,
        "split_orientation": orientation,
        "safe": bool(safe),
        "coverage_ratio": round(min_coverage, 4),
        "cut_risk_score": round(max_cut_risk, 4),
        "min_keyframe_safe_ratio": round(min_keyframe_safe_ratio, 4),
        "max_keyframe_cut_risk": round(max_keyframe_cut_risk, 4),
        "panels": panels,
        "validated_box_count": len(ordered),
        "panel_crop_overlap_ratio": leak_guard.get("panel_crop_overlap_ratio", 0.0),
        "cross_panel_subject_leak": leak_guard.get("cross_panel_subject_leak", []),
        "max_cross_panel_leak_ratio": leak_guard.get("max_cross_panel_leak_ratio", 0.0),
        "split_rejection_reason": (
            None
            if safe
            else (
                "reject_split_duplicate_object_in_panels"
                if not leak_guard.get("safe", True)
                else (
                    "reject_split_keyframe_position_unsafe"
                    if (
                        min_keyframe_safe_ratio < FRAME_POSITION_MIN_COVERAGE
                        or max_keyframe_cut_risk > FRAME_POSITION_MAX_PANEL_CUT_RISK
                    )
                    else "reject_split_frame_position_unsafe"
                )
            )
        ),
    }


def apply_frame_position_pan_to_subjects(
    subjects: List[Dict[str, Any]],
    frame_position: Dict[str, Any],
) -> List[Dict[str, Any]]:
    panels = frame_position.get("panels") or []
    if not panels:
        return [dict(subject) for subject in subjects]

    panel_by_track = {
        panel.get("track_id"): panel
        for panel in panels
        if panel.get("track_id") is not None
    }

    adjusted: List[Dict[str, Any]] = []
    for subject in subjects:
        copied = dict(subject)
        panel = panel_by_track.get(subject.get("track_id"))
        if panel and "pan" in panel:
            copied["raw_pan_before_frame_position"] = copied.get("pan")
            copied["pan"] = panel["pan"]
            copied["face_safe_pan"] = panel["pan"]
            copied["frame_position_panel"] = panel.get("panel")
        adjusted.append(copied)

    return adjusted


def decide_layout(
    reliable: List[Dict[str, Any]],
    subjects: List[Dict[str, Any]],
    frame_width: int,
    frame_height: int,
    text: str,
    multi_face_frame_ratio: float,
) -> Dict[str, Any]:
    dialog_density = compute_dialog_density(text)

    ranked_source = reliable if reliable else [
        subject for subject in subjects if is_weak_subject(subject)
    ]

    ranked = sorted(
        ranked_source,
        key=lambda subject: (
            subject.get("active_speaker_score", 0.0),
            subject.get("score", 0.0),
            subject.get("persistence", 0.0),
        ),
        reverse=True,
    )

    if not ranked:
        frame_position = evaluate_wide_context_frame_position(
            None,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        return {
            "layout": LAYOUT_WIDE_CONTEXT,
            "layout_variant": VARIANT_WIDE_CENTER,
            "angle": ANGLE_BASELINE,
            "reason": "no_subject_detected_use_wide_center_baseline",
            "pan": BASELINE_WIDE_CENTER_PAN,
            "selected": [],
            "dialog_density": dialog_density,
            "split_rejection_reason": "no_subject_detected",
            "angle_evidence": {
                "mode": "baseline",
                "angle_confidence": 0.0,
                "rejection_reason": "no_subject_detected",
            },
            "frame_position": frame_position,
            "focus_safety": {
                "mode": "wide_center_baseline",
                "raw_pan": BASELINE_WIDE_CENTER_PAN,
                "face_safe_pan": BASELINE_WIDE_CENTER_PAN,
                "wide_locked_pan": BASELINE_WIDE_CENTER_PAN,
            },
        }

    top = ranked[0]
    split_rejection: Optional[str] = None

    if len(ranked) >= 2:
        second = ranked[1]
        split_orientation = split_orientation_from_subjects(
            top,
            second,
            frame_width,
            frame_height,
        )

        is_valid_dual, dual_reason = is_dual_active_pair_valid(
            top=top,
            second=second,
            multi_face_frame_ratio=multi_face_frame_ratio,
            orientation=split_orientation,
            frame_width=frame_width,
            frame_height=frame_height,
        )

        if is_valid_dual:
            split_frame_evidence = validate_split_frame_evidence(
                top,
                second,
                orientation=split_orientation,
                frame_width=frame_width,
                frame_height=frame_height,
            )
            if not split_frame_evidence.get("safe", False):
                split_rejection = (
                    split_frame_evidence.get("rejection_reason")
                    or f"{dual_reason}_but_frame_evidence_unsafe"
                )
            else:
                selected = sorted(
                    [top, second],
                    key=(
                        (lambda item: box_center(subject_safety_box(item), frame_width, frame_height)[1])
                        if split_orientation == "top_bottom"
                        else (lambda item: item["pan"])
                    ),
                )
                pan = round((selected[0]["pan"] + selected[1]["pan"]) / 2, 4)
                frame_position = evaluate_split_frame_position(
                    selected,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    orientation=split_orientation,
                )
                frame_position["split_frame_evidence"] = split_frame_evidence

                if not frame_position.get("safe", False):
                    split_rejection = (
                        frame_position.get("split_rejection_reason")
                        or f"{dual_reason}_but_frame_position_unsafe"
                    )
                else:
                    selected = apply_frame_position_pan_to_subjects(
                        selected,
                        frame_position,
                    )
                    pan = round(
                        safe_mean([
                            float(subject.get("pan", BASELINE_WIDE_CENTER_PAN))
                            for subject in selected
                        ], BASELINE_WIDE_CENTER_PAN),
                        4,
                    )
                    layout = (
                        LAYOUT_SPLIT_TOP_BOTTOM
                        if split_orientation == "top_bottom"
                        else LAYOUT_SPLIT_LEFT_RIGHT
                    )
                    layout_variant = (
                        VARIANT_DUAL_SPLIT_TB
                        if split_orientation == "top_bottom"
                        else VARIANT_DUAL_SPLIT_LR
                    )
                    angle = (
                        ANGLE_3_DUAL_TB
                        if split_orientation == "top_bottom"
                        else ANGLE_3_DUAL_LR
                    )

                    return {
                        "layout": layout,
                        "layout_legacy": LAYOUT_SPLIT_COMPAT,
                        "layout_variant": layout_variant,
                        "split_orientation": split_orientation,
                        "visual_split_orientation": split_orientation,
                        "subject_distribution": split_orientation,
                        "angle": angle,
                        "reason": f"two_active_subjects_{split_orientation}_safe_split",
                        "pan": pan,
                        "selected": selected,
                        "dialog_density": dialog_density,
                        "split_rejection_reason": None,
                        "angle_evidence": {
                            "mode": "dual_split_frame_evidence",
                            **split_frame_evidence,
                        },
                        "frame_position": frame_position,
                        "focus_safety": {
                            "mode": f"dual_active_{split_orientation}_split",
                            "first_subject_pan": selected[0].get("face_safe_pan", selected[0]["pan"]),
                            "second_subject_pan": selected[1].get("face_safe_pan", selected[1]["pan"]),
                            "first_track_id": selected[0].get("track_id"),
                            "second_track_id": selected[1].get("track_id"),
                            "first_subject_side": subject_side(selected[0]),
                            "second_subject_side": subject_side(selected[1]),
                            "frame_position_safe": frame_position.get("safe"),
                        },
                    }

        if split_rejection is None:
            split_rejection = dual_reason
    else:
        split_rejection = "only_one_subject_candidate"

    wide_locked_pan = compute_wide_locked_pan(top)
    tight_frame_position = evaluate_single_frame_position(
        top,
        frame_width=frame_width,
        frame_height=frame_height,
        preferred_pan=wide_locked_pan,
    )
    frame_position = evaluate_wide_context_frame_position(
        top,
        frame_width=frame_width,
        frame_height=frame_height,
        preferred_pan=wide_locked_pan,
    )
    if not tight_frame_position.get("safe", False):
        split_rejection = f"{split_rejection}|tight_crop_unsafe_use_wide_fit_blur"
    if ADAPTIVE_ZOOM_ENABLED:
        adaptive_frame_position = evaluate_adaptive_zoom_frame_position(
            top,
            frame_width=frame_width,
            frame_height=frame_height,
            preferred_pan=wide_locked_pan,
        )
        if adaptive_frame_position.get("safe", False):
            frame_position = adaptive_frame_position
            wide_locked_pan = float(
                adaptive_frame_position.get("recommended_pan", wide_locked_pan)
            )
    angle_evidence = subject_frame_angle_evidence(top)
    side = str(angle_evidence.get("dominant_side") or subject_side(top))

    if side == "left" and angle_evidence.get("safe_for_non_center_angle", False):
        layout_variant = VARIANT_SINGLE_LEFT
        angle = ANGLE_1_LEFT
        reason = "single_active_subject_left_wide_context_locked"
    elif side == "right" and angle_evidence.get("safe_for_non_center_angle", False):
        layout_variant = VARIANT_SINGLE_RIGHT
        angle = ANGLE_2_RIGHT
        reason = "single_active_subject_right_wide_context_locked"
    else:
        layout_variant = VARIANT_WIDE_SUBJECT_SAFE
        angle = ANGLE_4_SUBJECT_SAFE
        reason = (
            "subject_center_or_uncertain_wide_context_subject_safe"
            if angle_evidence.get("safe_for_non_center_angle", False)
            else f"angle_evidence_weak_{angle_evidence.get('rejection_reason')}"
        )

    if not reliable:
        layout_variant = VARIANT_WIDE_SUBJECT_SAFE
        angle = ANGLE_4_SUBJECT_SAFE
        reason = "weak_subject_candidate_use_wide_context_subject_safe"

    return {
        "layout": LAYOUT_WIDE_CONTEXT,
        "layout_variant": layout_variant,
        "angle": angle,
        "reason": reason,
        "pan": wide_locked_pan,
        "selected": [top],
        "dialog_density": dialog_density,
        "split_rejection_reason": split_rejection,
        "angle_evidence": angle_evidence,
        "frame_position": frame_position,
        "focus_safety": {
            "mode": "wide_context_subject_locked",
            "raw_pan": top.get("pan", BASELINE_WIDE_CENTER_PAN),
            "face_safe_pan": top.get("face_safe_pan", top.get("pan", BASELINE_WIDE_CENTER_PAN)),
            "wide_locked_pan": wide_locked_pan,
            "subject_side": side,
            "selected_track_id": top.get("track_id"),
            "adaptive_zoom_enabled": bool(frame_position.get("adaptive_zoom_enabled", False)),
            "adaptive_zoom": frame_position.get("zoom", 1.0),
            "adaptive_zoom_rejection_reason": frame_position.get("adaptive_zoom_rejection_reason"),
        },
    }


# ============================================================
# FADE CENTER / PAN SMOOTHING
# ============================================================

def smoothstep(value: float) -> float:
    value = clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * clamp(t, 0.0, 1.0)


def apply_pan_deadzone(current_pan: float, target_pan: float) -> float:
    if abs(target_pan - current_pan) < PAN_DEADZONE:
        return current_pan
    return target_pan


def limit_pan_step(previous_pan: float, target_pan: float) -> float:
    delta = target_pan - previous_pan

    if abs(delta) <= MAX_PAN_STEP_PER_CLIP:
        return target_pan

    if delta > 0:
        return previous_pan + MAX_PAN_STEP_PER_CLIP

    return previous_pan - MAX_PAN_STEP_PER_CLIP


def estimate_plan_duration_seconds(plan: Dict[str, Any]) -> float:
    start = plan.get("start_time")
    end = plan.get("end_time")

    if start is None or end is None:
        return 0.5

    try:
        return max(0.1, float(end) - float(start))
    except Exception:
        return 0.5


def compute_fade_center_pan(
    previous_pan: float,
    target_pan: float,
    has_subject: bool,
    face_missing_duration: float = 0.0,
) -> Tuple[float, Dict[str, Any]]:
    previous_pan = clamp(previous_pan, PAN_MIN, PAN_MAX)
    target_pan = clamp(target_pan, PAN_MIN, PAN_MAX)

    if has_subject:
        blended = lerp(previous_pan, target_pan, SUBJECT_LOCK_STRENGTH)
        blended = apply_pan_deadzone(previous_pan, blended)
        blended = limit_pan_step(previous_pan, blended)

        return round(clamp(blended, PAN_MIN, PAN_MAX), 4), {
            "mode": "subject_lock",
            "previous_pan": round(previous_pan, 4),
            "target_pan": round(target_pan, 4),
            "strength": SUBJECT_LOCK_STRENGTH,
            "face_missing_duration": round(face_missing_duration, 3),
        }

    if face_missing_duration <= FACE_LOCK_HOLD_SECONDS:
        return round(previous_pan, 4), {
            "mode": "hold_last_known_pan",
            "previous_pan": round(previous_pan, 4),
            "target_pan": round(target_pan, 4),
            "face_missing_duration": round(face_missing_duration, 3),
            "hold_seconds": FACE_LOCK_HOLD_SECONDS,
        }

    fade_progress = min(
        1.0,
        (face_missing_duration - FACE_LOCK_HOLD_SECONDS) /
        max(FACE_LOCK_HOLD_SECONDS, 0.001),
    )

    fade_strength = smoothstep(fade_progress) * CENTER_FADE_STRENGTH
    blended = lerp(previous_pan, BASELINE_WIDE_CENTER_PAN, fade_strength)
    blended = limit_pan_step(previous_pan, blended)

    return round(clamp(blended, PAN_MIN, PAN_MAX), 4), {
        "mode": "fade_to_center",
        "previous_pan": round(previous_pan, 4),
        "target_pan": BASELINE_WIDE_CENTER_PAN,
        "fade_progress": round(fade_progress, 3),
        "fade_strength": round(fade_strength, 3),
        "face_missing_duration": round(face_missing_duration, 3),
    }


def apply_fade_center_to_plans(plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not FADE_CENTER_ENABLED:
        return plans

    previous_pan = BASELINE_WIDE_CENTER_PAN
    last_subject_pan = BASELINE_WIDE_CENTER_PAN
    face_missing_duration = 0.0

    processed: List[Dict[str, Any]] = []

    for plan in plans:
        layout_variant = plan.get("layout_variant")
        selected = plan.get("subjects") or []
        has_subject = bool(selected)

        raw_target_pan = float(plan.get("pan", BASELINE_WIDE_CENTER_PAN))

        if layout_variant in {VARIANT_DUAL_SPLIT_LR, VARIANT_DUAL_SPLIT_TB}:
            plan["raw_pan_before_fade_center"] = raw_target_pan
            plan["fade_center"] = {
                "mode": "skip_for_dual_split",
                "reason": "dual split uses subject panels, not global pan smoothing",
            }
            processed.append(plan)
            continue

        if layout_variant == VARIANT_WIDE_CENTER:
            target_pan = BASELINE_WIDE_CENTER_PAN
            has_subject = False
        elif has_subject:
            target_pan = raw_target_pan
            last_subject_pan = target_pan
            face_missing_duration = 0.0
        else:
            target_pan = last_subject_pan
            face_missing_duration += estimate_plan_duration_seconds(plan)

        smoothed_pan, fade_meta = compute_fade_center_pan(
            previous_pan=previous_pan,
            target_pan=target_pan,
            has_subject=has_subject,
            face_missing_duration=face_missing_duration,
        )

        plan["raw_pan_before_fade_center"] = raw_target_pan
        plan["pan"] = smoothed_pan
        plan["pan_start"] = previous_pan
        plan["pan_end"] = smoothed_pan
        plan["fade_center"] = fade_meta

        previous_pan = smoothed_pan
        processed.append(plan)

    return processed



# ============================================================
# DYNAMIC TIMELINE SEGMENT HELPERS
# ============================================================

def dynamic_segment_ranges(start: float, end: float) -> List[Tuple[float, float]]:
    """Split a highlight into short continuous visual-decision windows."""
    duration = max(0.0, end - start)

    if duration <= DYNAMIC_SEGMENT_SECONDS + DYNAMIC_MIN_SEGMENT_SECONDS:
        return [(start, end)]

    ranges: List[Tuple[float, float]] = []
    cursor = start

    while cursor < end:
        segment_end = min(end, cursor + DYNAMIC_SEGMENT_SECONDS)

        if end - segment_end < DYNAMIC_MIN_SEGMENT_SECONDS and ranges:
            previous_start, _ = ranges[-1]
            ranges[-1] = (previous_start, end)
            break

        ranges.append((cursor, segment_end))
        cursor = segment_end

    return ranges


def sample_times_for_dynamic_segment(start: float, end: float) -> List[float]:
    """Lower-cost sampling for short dynamic windows."""
    duration = max(0.1, end - start)
    count = int(duration * DYNAMIC_SEGMENT_SAMPLES_PER_SECOND)
    count = max(DYNAMIC_MIN_SAMPLE_COUNT, min(DYNAMIC_MAX_SAMPLE_COUNT, count))

    return [start + duration * (idx + 0.5) / count for idx in range(count)]


def read_frame_at_timestamp(cap: cv2.VideoCapture, timestamp: float):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000)
    ok, frame = cap.read()
    if not ok or frame is None:
        return None
    return frame


def compute_visual_metrics_from_frame(frame) -> Dict[str, Any]:
    if frame is None:
        return {
            "valid": False,
            "blur_laplacian": 0.0,
            "blur_score": 0.0,
            "brightness": 0.0,
            "edge_density": 0.0,
            "histogram": [],
        }

    small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    blur_laplacian = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blur_score = clamp(
        (blur_laplacian - BLUR_LAPLACIAN_LOW)
        / max(BLUR_LAPLACIAN_HIGH - BLUR_LAPLACIAN_LOW, 0.001)
    )

    brightness = float(gray.mean()) / 255.0
    edges = cv2.Canny(gray, 70, 150)
    edge_density = float((edges > 0).mean())

    hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
    hist = cv2.normalize(hist, hist).flatten()

    return {
        "valid": True,
        "blur_laplacian": round(blur_laplacian, 3),
        "blur_score": round(blur_score, 4),
        "brightness": round(brightness, 4),
        "edge_density": round(edge_density, 4),
        "histogram": [float(value) for value in hist],
    }


def compute_visual_metrics_at_timestamp(cap: cv2.VideoCapture, timestamp: float) -> Dict[str, Any]:
    frame = read_frame_at_timestamp(cap, timestamp)
    metrics = compute_visual_metrics_from_frame(frame)
    metrics["timestamp"] = round(timestamp, 3)
    return metrics


def histogram_difference(first_hist: List[float], second_hist: List[float]) -> float:
    if not first_hist or not second_hist or len(first_hist) != len(second_hist):
        return 0.0

    # Bhattacharyya distance is stable enough for simple shot-boundary detection.
    first = np.array(first_hist, dtype=np.float32)
    second = np.array(second_hist, dtype=np.float32)
    return float(cv2.compareHist(first, second, cv2.HISTCMP_BHATTACHARYYA))


def frame_histogram_difference(previous: Dict[str, Any], current: Dict[str, Any]) -> float:
    return round(histogram_difference(previous.get("histogram") or [], current.get("histogram") or []), 4)


def split_ranges_by_shot_boundaries(
    *,
    cap: cv2.VideoCapture,
    start: float,
    end: float,
) -> List[Tuple[float, float]]:
    """Split highlight by time windows plus hard/soft scene cuts."""
    if not SHOT_BOUNDARY_ENABLED or end <= start:
        return dynamic_segment_ranges(start, end)

    probe_times: List[float] = []
    cursor = start
    while cursor <= end:
        probe_times.append(cursor)
        cursor += SHOT_BOUNDARY_SCAN_SECONDS

    if not probe_times or probe_times[-1] < end:
        probe_times.append(end)

    metrics = [compute_visual_metrics_at_timestamp(cap, timestamp) for timestamp in probe_times]
    cut_points = [start]

    for idx in range(1, len(metrics)):
        previous = metrics[idx - 1]
        current = metrics[idx]
        diff = frame_histogram_difference(previous, current)
        current_time = float(current.get("timestamp", probe_times[idx]))

        is_hard_cut = diff >= SHOT_BOUNDARY_HARD_DIFF
        is_soft_cut = (
            diff >= SHOT_BOUNDARY_SOFT_DIFF
            and float(current.get("blur_score", 1.0)) <= BLUR_WEAK_SCORE
        )

        if is_hard_cut or is_soft_cut:
            if current_time - cut_points[-1] >= SHOT_BOUNDARY_MIN_SEGMENT_SECONDS:
                if end - current_time >= SHOT_BOUNDARY_MIN_SEGMENT_SECONDS:
                    cut_points.append(current_time)

    if cut_points[-1] != end:
        cut_points.append(end)

    ranges: List[Tuple[float, float]] = []
    for left, right in zip(cut_points, cut_points[1:]):
        ranges.extend(dynamic_segment_ranges(left, right))

    # Normalize tiny fragments created by boundary + fixed-window split.
    normalized: List[Tuple[float, float]] = []
    for left, right in ranges:
        if normalized and right - left < DYNAMIC_MIN_SEGMENT_SECONDS:
            prev_left, _ = normalized[-1]
            normalized[-1] = (prev_left, right)
        else:
            normalized.append((left, right))

    return normalized or [(start, end)]


def summarize_visual_metrics(metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = [item for item in metrics if item.get("valid")]
    if not valid:
        return {
            "enabled": VISUAL_QUALITY_ENABLED,
            "valid_sample_count": 0,
            "avg_blur_score": 0.0,
            "min_blur_score": 0.0,
            "avg_brightness": 0.0,
            "avg_edge_density": 0.0,
            "is_bad_visual_segment": True,
            "reason": "no_valid_visual_samples",
        }

    blur_scores = [float(item.get("blur_score", 0.0)) for item in valid]
    brightness = [float(item.get("brightness", 0.0)) for item in valid]
    edge_density = [float(item.get("edge_density", 0.0)) for item in valid]

    avg_blur = safe_mean(blur_scores)
    min_blur = min(blur_scores) if blur_scores else 0.0

    is_bad = avg_blur <= BLUR_BAD_SCORE or min_blur <= BLUR_BAD_SCORE * 0.72
    if is_bad:
        reason = "blurred_or_transition_segment"
    elif avg_blur <= BLUR_WEAK_SCORE:
        reason = "weak_blur_score"
    else:
        reason = "visual_quality_ok"

    return {
        "enabled": VISUAL_QUALITY_ENABLED,
        "valid_sample_count": len(valid),
        "avg_blur_score": round(avg_blur, 4),
        "min_blur_score": round(min_blur, 4),
        "avg_brightness": round(safe_mean(brightness), 4),
        "avg_edge_density": round(safe_mean(edge_density), 4),
        "is_bad_visual_segment": bool(is_bad),
        "reason": reason,
        "samples": [
            {
                "timestamp": item.get("timestamp"),
                "blur_score": item.get("blur_score"),
                "blur_laplacian": item.get("blur_laplacian"),
                "brightness": item.get("brightness"),
                "edge_density": item.get("edge_density"),
            }
            for item in valid[:8]
        ],
    }


def should_force_wide_center_for_visual_quality(
    visual_quality: Dict[str, Any],
    face_count: int,
) -> bool:
    if not VISUAL_QUALITY_ENABLED or not BAD_VISUAL_FORCE_WIDE_CENTER:
        return False

    if not visual_quality.get("is_bad_visual_segment"):
        return False

    return face_count <= BAD_VISUAL_FACE_COUNT_MAX


def make_dynamic_reframe_guard() -> Dict[str, Any]:
    return {
        "dynamic_layout_enabled": DYNAMIC_LAYOUT_ENABLED,
        "dynamic_segment_seconds": DYNAMIC_SEGMENT_SECONDS,
        "dynamic_min_segment_seconds": DYNAMIC_MIN_SEGMENT_SECONDS,
        "dynamic_segment_samples_per_second": DYNAMIC_SEGMENT_SAMPLES_PER_SECOND,
        "dynamic_min_sample_count": DYNAMIC_MIN_SAMPLE_COUNT,
        "dynamic_max_sample_count": DYNAMIC_MAX_SAMPLE_COUNT,
        "min_dynamic_layout_duration_seconds": MIN_DYNAMIC_LAYOUT_DURATION_SECONDS,
        "pan_merge_tolerance": PAN_MERGE_TOLERANCE,
        "pan_split_merge_tolerance": PAN_SPLIT_MERGE_TOLERANCE,
        "wide_center_baseline_enabled": True,
        "wide_center_reference": "visual_layout_analyzer copy.py",
        "face_safe_enabled": FACE_SAFE_ENABLED,
        "safe_pan_min": SAFE_PAN_MIN,
        "safe_pan_max": SAFE_PAN_MAX,
        "edge_face_box_margin_ratio": EDGE_FACE_BOX_MARGIN_RATIO,
        "edge_face_pan_push": EDGE_FACE_PAN_PUSH,
        "speaker_look_room": SPEAKER_LOOK_ROOM,
        "wide_lock_subject_weight": WIDE_LOCK_SUBJECT_WEIGHT,
        "edge_wide_lock_subject_weight": EDGE_WIDE_LOCK_SUBJECT_WEIGHT,
        "left_right_split_min_distance": LEFT_RIGHT_SPLIT_MIN_DISTANCE,
        "dual_active_min_copresence": DUAL_ACTIVE_MIN_COPRESENCE,
        "dual_active_min_second_score": DUAL_ACTIVE_MIN_SECOND_SCORE,
        "dual_active_max_gap": DUAL_ACTIVE_MAX_GAP,
        "min_angle_side_vote_ratio": MIN_ANGLE_SIDE_VOTE_RATIO,
        "min_angle_confidence": MIN_ANGLE_CONFIDENCE,
        "min_angle_frame_sample_count": MIN_ANGLE_FRAME_SAMPLE_COUNT,
        "max_angle_pan_stdev": MAX_ANGLE_PAN_STDEV,
        "adaptive_zoom_enabled": ADAPTIVE_ZOOM_ENABLED,
        "adaptive_zoom_min": ADAPTIVE_ZOOM_MIN,
        "adaptive_zoom_max": ADAPTIVE_ZOOM_MAX,
        "adaptive_zoom_target": ADAPTIVE_ZOOM_TARGET,
        "adaptive_zoom_face_margin_ratio": ADAPTIVE_ZOOM_FACE_MARGIN_RATIO,
        "adaptive_zoom_max_keyframe_cut_risk": ADAPTIVE_ZOOM_MAX_KEYFRAME_CUT_RISK,
        "adaptive_zoom_min_keyframe_coverage": ADAPTIVE_ZOOM_MIN_KEYFRAME_COVERAGE,
        "min_split_frame_copresence_count": MIN_SPLIT_FRAME_COPRESENCE_COUNT,
        "min_split_frame_evidence_ratio": MIN_SPLIT_FRAME_EVIDENCE_RATIO,
        "max_split_frame_duplicate_ratio": MAX_SPLIT_FRAME_DUPLICATE_RATIO,
        "top_bottom_duplicate_max_pan_distance": TOP_BOTTOM_DUPLICATE_MAX_PAN_DISTANCE,
        "min_multi_face_frame_ratio_for_split": MIN_MULTI_FACE_FRAME_RATIO_FOR_SPLIT,
        "min_subject_co_presence_ratio_for_split": MIN_SUBJECT_CO_PRESENCE_RATIO_FOR_SPLIT,
        "same_subject_iou_threshold": SAME_SUBJECT_IOU_THRESHOLD,
        "same_subject_max_pan_distance": SAME_SUBJECT_MAX_PAN_DISTANCE,
        "same_subject_max_y_distance": SAME_SUBJECT_MAX_Y_DISTANCE,
        "same_subject_min_height_ratio": SAME_SUBJECT_MIN_HEIGHT_RATIO,
        "same_subject_min_area_ratio": SAME_SUBJECT_MIN_AREA_RATIO,
        "fade_center_enabled": FADE_CENTER_ENABLED,
        "visual_quality_enabled": VISUAL_QUALITY_ENABLED,
        "shot_boundary_enabled": SHOT_BOUNDARY_ENABLED,
        "shot_boundary_scan_seconds": SHOT_BOUNDARY_SCAN_SECONDS,
        "shot_boundary_hard_diff": SHOT_BOUNDARY_HARD_DIFF,
        "shot_boundary_soft_diff": SHOT_BOUNDARY_SOFT_DIFF,
        "blur_bad_score": BLUR_BAD_SCORE,
        "blur_weak_score": BLUR_WEAK_SCORE,
        "bad_visual_force_wide_center": BAD_VISUAL_FORCE_WIDE_CENTER,
        "frame_position_safety_enabled": FRAME_POSITION_SAFETY_ENABLED,
        "frame_position_target_aspect": round(FRAME_POSITION_TARGET_ASPECT, 5),
        "frame_position_split_panel_aspect": round(FRAME_POSITION_SPLIT_PANEL_ASPECT, 5),
        "frame_position_face_margin_ratio": FRAME_POSITION_FACE_MARGIN_RATIO,
        "frame_position_max_cut_risk": FRAME_POSITION_MAX_CUT_RISK,
        "frame_position_min_coverage": FRAME_POSITION_MIN_COVERAGE,
        "frame_position_max_panel_overlap_ratio": FRAME_POSITION_MAX_PANEL_OVERLAP_RATIO,
        "frame_position_max_cross_panel_leak_ratio": FRAME_POSITION_MAX_CROSS_PANEL_LEAK_RATIO,
    }


def create_plan_from_decision(
    *,
    clip_index: int,
    segment_index: int,
    start: float,
    end: float,
    decision: Dict[str, Any],
    subjects: List[Dict[str, Any]],
    reliable: List[Dict[str, Any]],
    multi_face_frame_ratio: float,
    frame_width: int,
    frame_height: int,
) -> Dict[str, Any]:
    duration = max(0.0, end - start)

    active_ranked = sorted(
        reliable,
        key=lambda subject: (
            subject.get("active_speaker_score", 0.0),
            subject.get("score", 0.0),
            subject.get("persistence", 0.0),
        ),
        reverse=True,
    )

    plan = {
        "clip_index": clip_index,
        "segment_index": segment_index,
        "timeline_type": "dynamic_segment",
        "start_time": round(start, 3),
        "end_time": round(end, 3),
        "clip_start": round(start, 3),
        "clip_end": round(end, 3),
        "clip_duration": round(duration, 3),

        "layout": decision["layout"],
        "layout_legacy": decision.get("layout_legacy"),
        "layout_variant": decision["layout_variant"],
        "angle": decision["angle"],
        "layout_reason": decision["reason"],

        "split_orientation": decision.get("split_orientation"),
        "visual_split_orientation": decision.get("visual_split_orientation"),
        "subject_distribution": decision.get("subject_distribution"),
        "split_rejection_reason": decision["split_rejection_reason"],

        "pan": decision["pan"],
        "pan_start": decision["pan"],
        "pan_end": decision["pan"],

        "dialog_density": round(decision["dialog_density"], 3),
        "multi_face_frame_ratio": multi_face_frame_ratio,

        "frame_width": frame_width,
        "frame_height": frame_height,

        "subjects": decision["selected"],
        "all_subjects": subjects,
        "active_speaker_rank": active_ranked[:3],

        "focus_safety": decision["focus_safety"],
        "frame_position": decision.get("frame_position", {}),
        "angle_evidence": decision.get("angle_evidence", {}),

        "motion": {
            "type": (
                "dual_active_top_bottom_split"
                if decision["layout_variant"] == VARIANT_DUAL_SPLIT_TB
                else "dual_active_left_right_split"
            )
            if decision["layout_variant"] in {VARIANT_DUAL_SPLIT_LR, VARIANT_DUAL_SPLIT_TB}
            else (
                "wide_context_subject_lock"
                if decision["layout_variant"] != VARIANT_WIDE_CENTER
                else "locked_center"
            ),
            "duration": round(duration, 3),
            "pan_start": decision["pan"],
            "pan_end": decision["pan"],
        },

        "dynamic_reframe_guard": make_dynamic_reframe_guard(),
    }

    if decision["layout_variant"] == VARIANT_WIDE_CENTER:
        baseline = make_baseline_wide_center_plan(
            index=clip_index,
            start=start,
            end=end,
            frame_width=frame_width,
            frame_height=frame_height,
            reason=decision["reason"],
            dialog_density=decision["dialog_density"],
        )
        baseline.update(
            {
                "segment_index": segment_index,
                "timeline_type": "dynamic_segment",
                "dynamic_reframe_guard": make_dynamic_reframe_guard(),
            }
        )
        return baseline

    return plan


def analyze_visual_segment(
    *,
    cap: cv2.VideoCapture,
    frontal_cascade: cv2.CascadeClassifier,
    profile_cascade: cv2.CascadeClassifier,
    clip_index: int,
    segment_index: int,
    start: float,
    end: float,
    text: str,
    frame_width: int,
    frame_height: int,
) -> Dict[str, Any]:
    faces: List[Dict[str, Any]] = []
    visual_metric_samples: List[Dict[str, Any]] = []
    timestamps = sample_times_for_dynamic_segment(start, end)

    for timestamp in timestamps:
        frame = read_frame_at_timestamp(cap, timestamp)

        if VISUAL_QUALITY_ENABLED:
            metrics = compute_visual_metrics_from_frame(frame)
            metrics["timestamp"] = round(timestamp, 3)
            visual_metric_samples.append(metrics)

        faces.extend(
            detect_faces_in_frame(
                frame=frame,
                frontal_cascade=frontal_cascade,
                profile_cascade=profile_cascade,
                frame_width=frame_width,
                frame_height=frame_height,
                timestamp=timestamp,
            )
        )

    visual_quality = summarize_visual_metrics(visual_metric_samples) if VISUAL_QUALITY_ENABLED else {
        "enabled": False,
        "is_bad_visual_segment": False,
        "reason": "disabled",
    }

    if should_force_wide_center_for_visual_quality(visual_quality, len(faces)):
        plan = make_baseline_wide_center_plan(
            index=clip_index,
            start=start,
            end=end,
            frame_width=frame_width,
            frame_height=frame_height,
            reason=f"bad_visual_quality_force_wide_center_{visual_quality.get('reason')}",
            dialog_density=compute_dialog_density(text),
        )
        plan.update(
            {
                "segment_index": segment_index,
                "timeline_type": "dynamic_segment",
                "visual_quality": visual_quality,
                "raw_detected_face_count": len(faces),
                "dynamic_reframe_guard": make_dynamic_reframe_guard(),
            }
        )
        return plan

    cluster_result = cluster_faces(
        faces,
        frame_width=frame_width,
        frame_height=frame_height,
    )
    subjects = cluster_result["subjects"]
    multi_face_frame_ratio = cluster_result["multi_face_frame_ratio"]

    reliable = sorted(
        [subject for subject in subjects if is_reliable_subject(subject, frame_height)],
        key=lambda subject: subject["pan"],
    )

    decision = decide_layout(
        reliable=reliable,
        subjects=subjects,
        frame_width=frame_width,
        frame_height=frame_height,
        text=text,
        multi_face_frame_ratio=multi_face_frame_ratio,
    )

    plan = create_plan_from_decision(
        clip_index=clip_index,
        segment_index=segment_index,
        start=start,
        end=end,
        decision=decision,
        subjects=subjects,
        reliable=reliable,
        multi_face_frame_ratio=multi_face_frame_ratio,
        frame_width=frame_width,
        frame_height=frame_height,
    )
    plan["visual_quality"] = visual_quality
    plan["raw_detected_face_count"] = len(faces)
    return plan


def plan_duration(plan: Dict[str, Any]) -> float:
    try:
        return max(0.0, float(plan.get("end_time", 0.0)) - float(plan.get("start_time", 0.0)))
    except Exception:
        return 0.0


def is_split_plan(plan: Dict[str, Any]) -> bool:
    return plan.get("layout_variant") in {VARIANT_DUAL_SPLIT_LR, VARIANT_DUAL_SPLIT_TB}


def copy_layout_decision(source: Dict[str, Any], target: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Copy only visual decision fields, preserving target time range."""
    for key in [
        "layout",
        "layout_legacy",
        "layout_variant",
        "angle",
        "layout_reason",
        "split_orientation",
        "visual_split_orientation",
        "subject_distribution",
        "split_rejection_reason",
        "pan",
        "subjects",
        "focus_safety",
        "frame_position",
        "angle_evidence",
        "motion",
    ]:
        if key in source:
            target[key] = source[key]

    target["layout_reason"] = f"{target.get('layout_reason', '')}|hysteresis_{reason}"
    target["hysteresis_applied"] = True
    target["hysteresis_source_segment_index"] = source.get("segment_index")
    return target


def apply_layout_hysteresis_to_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Suppress short isolated layout spikes to avoid flicker."""
    if len(segments) < 3:
        return segments

    processed = [dict(segment) for segment in segments]

    for idx in range(1, len(processed) - 1):
        previous = processed[idx - 1]
        current = processed[idx]
        following = processed[idx + 1]

        current_duration = plan_duration(current)
        if current_duration >= MIN_DYNAMIC_LAYOUT_DURATION_SECONDS:
            continue

        previous_variant = previous.get("layout_variant")
        current_variant = current.get("layout_variant")
        following_variant = following.get("layout_variant")

        # Example: wide -> split -> wide in only 1 segment.
        # Most likely detector noise, not a real cinematic layout change.
        if previous_variant == following_variant and current_variant != previous_variant:
            processed[idx] = copy_layout_decision(
                source=previous,
                target=current,
                reason="short_isolated_layout_spike",
            )
            continue

        # Be stricter for split: split must survive more than one tiny window.
        if is_split_plan(current) and not is_split_plan(previous) and not is_split_plan(following):
            processed[idx] = copy_layout_decision(
                source=previous,
                target=current,
                reason="isolated_split_rejected",
            )

    return processed


def segment_signature(segment: Dict[str, Any]) -> Tuple[Any, ...]:
    if segment.get("layout") == LAYOUT_WIDE_CONTEXT:
        frame_position = segment.get("frame_position") or {}
        return (
            LAYOUT_WIDE_CONTEXT,
            segment.get("layout_variant", VARIANT_WIDE_CENTER),
            segment.get("angle", ANGLE_BASELINE),
            frame_position.get("render_mode", "wide_fit_blur"),
        )

    return (
        segment.get("layout"),
        segment.get("layout_variant"),
        segment.get("split_orientation"),
        len(segment.get("subjects") or []),
    )


def can_merge_segments(previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
    if segment_signature(previous) != segment_signature(current):
        return False

    if (
        previous.get("layout") == LAYOUT_WIDE_CONTEXT
        and current.get("layout") == LAYOUT_WIDE_CONTEXT
        and (previous.get("frame_position") or {}).get("render_mode") == "wide_fit_blur"
        and (current.get("frame_position") or {}).get("render_mode") == "wide_fit_blur"
    ):
        return True

    previous_frame_position = previous.get("frame_position") or {}
    current_frame_position = current.get("frame_position") or {}
    if (
        float(previous_frame_position.get("cut_risk_score", 0.0)) > FRAME_POSITION_MAX_CUT_RISK
        or float(current_frame_position.get("cut_risk_score", 0.0)) > FRAME_POSITION_MAX_CUT_RISK
    ):
        return False

    previous_subjects = sorted(
        previous.get("subjects") or [],
        key=lambda item: str(item.get("track_id", "")),
    )
    current_subjects = sorted(
        current.get("subjects") or [],
        key=lambda item: str(item.get("track_id", "")),
    )

    if len(previous_subjects) == len(current_subjects) and previous_subjects:
        for previous_subject, current_subject in zip(previous_subjects, current_subjects):
            previous_box = subject_safety_box(previous_subject)
            current_box = subject_safety_box(current_subject)
            if valid_box(previous_box) and valid_box(current_box):
                pan_shift = abs(
                    float(previous_subject.get("pan", BASELINE_WIDE_CENTER_PAN))
                    - float(current_subject.get("pan", BASELINE_WIDE_CENTER_PAN))
                )
                if box_iou(previous_box, current_box) < 0.42 and pan_shift > PAN_MERGE_TOLERANCE:
                    return False

    previous_pan = float(previous.get("pan", BASELINE_WIDE_CENTER_PAN))
    current_pan = float(current.get("pan", BASELINE_WIDE_CENTER_PAN))

    tolerance = PAN_SPLIT_MERGE_TOLERANCE if is_split_plan(previous) else PAN_MERGE_TOLERANCE
    return abs(previous_pan - current_pan) <= tolerance


def merge_two_segments(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(previous)
    previous_start = float(previous.get("start_time", previous.get("clip_start", 0.0)))
    current_end = float(current.get("end_time", current.get("clip_end", previous_start)))
    duration = max(0.0, current_end - previous_start)

    previous_duration = max(plan_duration(previous), 0.001)
    current_duration = max(plan_duration(current), 0.001)
    total_duration = previous_duration + current_duration

    previous_pan = float(previous.get("pan", BASELINE_WIDE_CENTER_PAN))
    current_pan = float(current.get("pan", BASELINE_WIDE_CENTER_PAN))
    weighted_pan = (
        previous_pan * previous_duration + current_pan * current_duration
    ) / max(total_duration, 0.001)

    merged["end_time"] = round(current_end, 3)
    merged["clip_end"] = round(current_end, 3)
    merged["clip_duration"] = round(duration, 3)
    merged["pan"] = round(clamp(weighted_pan, PAN_MIN, PAN_MAX), 4)
    merged["pan_end"] = current.get("pan_end", current.get("pan", merged["pan"]))
    merged["merged_segment_indices"] = (
        previous.get("merged_segment_indices") or [previous.get("segment_index")]
    ) + (current.get("merged_segment_indices") or [current.get("segment_index")])
    if "frame_position" in merged:
        merged["frame_position"] = dict(merged["frame_position"])
        merged["frame_position"]["recommended_pan"] = merged["pan"]
        merged["frame_position"]["merged_from_cut_risk_scores"] = [
            (previous.get("frame_position") or {}).get("cut_risk_score", 0.0),
            (current.get("frame_position") or {}).get("cut_risk_score", 0.0),
        ]
        merged["frame_position"]["cut_risk_score"] = round(
            max(
                float((previous.get("frame_position") or {}).get("cut_risk_score", 0.0)),
                float((current.get("frame_position") or {}).get("cut_risk_score", 0.0)),
            ),
            4,
        )

    if "motion" in merged:
        merged["motion"] = dict(merged["motion"])
        merged["motion"]["duration"] = round(duration, 3)
        merged["motion"]["pan_end"] = merged["pan_end"]

    return merged


def merge_adjacent_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not segments:
        return []

    merged: List[Dict[str, Any]] = [segments[0]]

    for segment in segments[1:]:
        if can_merge_segments(merged[-1], segment):
            merged[-1] = merge_two_segments(merged[-1], segment)
        else:
            merged.append(segment)

    for idx, segment in enumerate(merged, start=1):
        segment["segment_index"] = idx

    return merged


def choose_representative_segment(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not segments:
        return {}

    def rank(segment: Dict[str, Any]) -> Tuple[float, float, float]:
        selected = segment.get("subjects") or []
        subject_score = max(
            [float(subject.get("active_speaker_score", 0.0)) for subject in selected],
            default=0.0,
        )
        split_bonus = 0.12 if is_split_plan(segment) else 0.0
        return (plan_duration(segment), subject_score + split_bonus, float(segment.get("multi_face_frame_ratio", 0.0)))

    return max(segments, key=rank)


def summarize_dynamic_segments(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = max(sum(plan_duration(segment) for segment in segments), 0.001)
    by_variant: Dict[str, float] = {}

    for segment in segments:
        variant = str(segment.get("layout_variant", "unknown"))
        by_variant[variant] = by_variant.get(variant, 0.0) + plan_duration(segment)

    bad_visual_segments = sum(
        1 for segment in segments
        if (segment.get("visual_quality") or {}).get("is_bad_visual_segment")
    )

    return {
        "segment_count": len(segments),
        "bad_visual_segment_count": bad_visual_segments,
        "layout_duration_ratio": {
            key: round(value / total, 4)
            for key, value in sorted(by_variant.items(), key=lambda item: item[0])
        },
        "has_dynamic_split": any(is_split_plan(segment) for segment in segments),
        "has_dynamic_split_lr": any(
            segment.get("layout_variant") == VARIANT_DUAL_SPLIT_LR
            for segment in segments
        ),
        "has_dynamic_split_tb": any(
            segment.get("layout_variant") == VARIANT_DUAL_SPLIT_TB
            for segment in segments
        ),
        "has_subject_lock": any(
            segment.get("layout_variant")
            in {VARIANT_SINGLE_LEFT, VARIANT_SINGLE_RIGHT, VARIANT_WIDE_SUBJECT_SAFE}
            for segment in segments
        ),
        "max_cut_risk_score": round(
            max(
                [
                    float((segment.get("frame_position") or {}).get("cut_risk_score", 0.0))
                    for segment in segments
                ],
                default=0.0,
            ),
            4,
        ),
    }


def build_dynamic_clip_plan(
    *,
    clip_index: int,
    start: float,
    end: float,
    frame_width: int,
    frame_height: int,
    segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    duration = max(0.0, end - start)

    if not segments:
        return make_baseline_wide_center_plan(
            index=clip_index,
            start=start,
            end=end,
            frame_width=frame_width,
            frame_height=frame_height,
            reason="no_dynamic_segments_generated_use_wide_center_baseline",
        )

    representative = choose_representative_segment(segments)
    first_segment = segments[0]

    # Top-level fields remain for backward compatibility, but renderer should
    # prefer segments/dynamic_segments when layout_mode == dynamic_timeline.
    return {
        "clip_index": clip_index,
        "timeline_type": "dynamic_clip",
        "layout_mode": "dynamic_timeline",
        "start_time": round(start, 3),
        "end_time": round(end, 3),
        "clip_start": round(start, 3),
        "clip_end": round(end, 3),
        "clip_duration": round(duration, 3),

        "layout": first_segment.get("layout", LAYOUT_WIDE_CONTEXT),
        "layout_legacy": first_segment.get("layout_legacy"),
        "layout_variant": first_segment.get("layout_variant", VARIANT_WIDE_CENTER),
        "angle": first_segment.get("angle", ANGLE_BASELINE),
        "layout_reason": "dynamic_timeline_use_segments_not_static_clip_layout",
        "split_orientation": first_segment.get("split_orientation"),
        "split_rejection_reason": first_segment.get("split_rejection_reason"),

        "pan": first_segment.get("pan", BASELINE_WIDE_CENTER_PAN),
        "pan_start": first_segment.get("pan_start", first_segment.get("pan", BASELINE_WIDE_CENTER_PAN)),
        "pan_end": segments[-1].get("pan_end", segments[-1].get("pan", BASELINE_WIDE_CENTER_PAN)),

        "dialog_density": round(safe_mean([float(segment.get("dialog_density", 0.0)) for segment in segments]), 3),
        "multi_face_frame_ratio": round(safe_mean([float(segment.get("multi_face_frame_ratio", 0.0)) for segment in segments]), 3),

        "frame_width": frame_width,
        "frame_height": frame_height,

        "subjects": representative.get("subjects", []),
        "all_subjects": representative.get("all_subjects", []),
        "active_speaker_rank": representative.get("active_speaker_rank", []),
        "focus_safety": representative.get("focus_safety", {}),

        "motion": {
            "type": "dynamic_timeline",
            "duration": round(duration, 3),
            "pan_start": first_segment.get("pan_start", first_segment.get("pan", BASELINE_WIDE_CENTER_PAN)),
            "pan_end": segments[-1].get("pan_end", segments[-1].get("pan", BASELINE_WIDE_CENTER_PAN)),
        },

        "segments": segments,
        "dynamic_segments": segments,
        "dynamic_summary": summarize_dynamic_segments(segments),
        "dynamic_reframe_guard": make_dynamic_reframe_guard(),
    }


def analyze_clip_dynamic_timeline(
    *,
    cap: cv2.VideoCapture,
    frontal_cascade: cv2.CascadeClassifier,
    profile_cascade: cv2.CascadeClassifier,
    clip_index: int,
    start: float,
    end: float,
    text: str,
    frame_width: int,
    frame_height: int,
) -> Dict[str, Any]:
    raw_segments: List[Dict[str, Any]] = []

    segment_ranges = split_ranges_by_shot_boundaries(
        cap=cap,
        start=start,
        end=end,
    )

    for segment_index, (segment_start, segment_end) in enumerate(segment_ranges, start=1):
        raw_segments.append(
            analyze_visual_segment(
                cap=cap,
                frontal_cascade=frontal_cascade,
                profile_cascade=profile_cascade,
                clip_index=clip_index,
                segment_index=segment_index,
                start=segment_start,
                end=segment_end,
                text=text,
                frame_width=frame_width,
                frame_height=frame_height,
            )
        )

    stable_segments = apply_layout_hysteresis_to_segments(raw_segments)
    stable_segments = apply_fade_center_to_plans(stable_segments)
    merged_segments = merge_adjacent_segments(stable_segments)

    return build_dynamic_clip_plan(
        clip_index=clip_index,
        start=start,
        end=end,
        frame_width=frame_width,
        frame_height=frame_height,
        segments=merged_segments,
    )

# ============================================================
# MAIN
# ============================================================

def main_analyzer() -> None:
    import logging
    import sys
    
    # Setup logging for CLI
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stdout
    )
    logger = logging.getLogger(__name__)
    
    if len(sys.argv) != 4:
        logger.error("Usage: visual_layout_analyzer.py <result.json> <video_file> <run_dir>")
        raise SystemExit(
            "Usage: visual_layout_analyzer.py <result.json> <video_file> <run_dir>"
        )

    result_path = Path(sys.argv[1])
    video_file = sys.argv[2]
    run_dir = Path(sys.argv[3])
    
    logger.info("Starting visual layout analysis...")
    logger.info(f"  result_json: {sys.argv[1]}")
    logger.info(f"  video_file: {sys.argv[2]}")
    logger.info(f"  run_dir: {sys.argv[3]}")

    data = json.loads(result_path.read_text(encoding="utf-8"))
    
    highlight_count = len(data.get("highlights", []))
    logger.info(f"Loaded {highlight_count} highlights from result.json")

    cap = cv2.VideoCapture(video_file)

    if not cap.isOpened():
        raise SystemExit(f"Cannot open video: {video_file}")

    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    frontal_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    profile_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_profileface.xml"
    )

    if frontal_cascade.empty():
        cap.release()
        raise SystemExit("Cannot load haarcascade_frontalface_default.xml")

    if profile_cascade.empty():
        cap.release()
        raise SystemExit("Cannot load haarcascade_profileface.xml")

    plans: List[Dict[str, Any]] = []

    for idx, item in enumerate(data.get("highlights", []), start=1):
        start = parse_time_value(item["start_time"])
        end = parse_time_value(item["end_time"])
        text = item.get("text", "")

        plan = analyze_clip_dynamic_timeline(
            cap=cap,
            frontal_cascade=frontal_cascade,
            profile_cascade=profile_cascade,
            clip_index=idx,
            start=start,
            end=end,
            text=text,
            frame_width=frame_width,
            frame_height=frame_height,
        )

        item["crop_plan"] = plan
        plans.append(plan)

    cap.release()

    highlights = data.get("highlights", [])
    for idx, plan in enumerate(plans):
        if idx < len(highlights) and isinstance(highlights[idx], dict):
            highlights[idx]["crop_plan"] = plan

    run_dir.mkdir(parents=True, exist_ok=True)

    crop_plan_path = run_dir / "crop_plan.json"

    crop_plan_path.write_text(
        json.dumps(
            {
                "mode": "dynamic-four-angle-wide-context-system",
                "layout_mode": "dynamic_timeline",
                "baseline": {
                    "layout": LAYOUT_WIDE_CONTEXT,
                    "layout_variant": VARIANT_WIDE_CENTER,
                    "pan": BASELINE_WIDE_CENTER_PAN,
                    "reason": "wide_context center is mandatory fallback when subject decision is ambiguous",
                },
                "layout_contract": {
                    "renderer_should_prefer": [
                        "clips[].segments",
                        "clips[].dynamic_segments",
                        "layout_variant",
                        "split_orientation",
                    ],
                    "legacy_static_fields": [
                        "layout",
                        "layout_legacy",
                        "pan",
                    ],
                    "note": "Do not force top-level layout for the whole clip when segments are available.",
                },
                "angle_map": {
                    ANGLE_1_LEFT: VARIANT_SINGLE_LEFT,
                    ANGLE_2_RIGHT: VARIANT_SINGLE_RIGHT,
                    ANGLE_3_DUAL_LR: VARIANT_DUAL_SPLIT_LR,
                    ANGLE_3_DUAL_TB: VARIANT_DUAL_SPLIT_TB,
                    ANGLE_4_SUBJECT_SAFE: VARIANT_WIDE_SUBJECT_SAFE,
                    ANGLE_BASELINE: VARIANT_WIDE_CENTER,
                },
                "layouts": {
                    "wide_context": LAYOUT_WIDE_CONTEXT,
                    "split_left_right": LAYOUT_SPLIT_LEFT_RIGHT,
                    "split_top_bottom": LAYOUT_SPLIT_TOP_BOTTOM,
                    "split_top_bottom_legacy": LAYOUT_SPLIT_TOP_BOTTOM,
                },
                "dynamic_config": make_dynamic_reframe_guard(),
                "clips": plans,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

print(crop_plan_path)
    
    clip_count = len(plans)
    logger.info(f"Visual layout analysis complete ({clip_count} clips)")
    logger.info(f"  crop_plan: {crop_plan_path}")


# ============================================================
# RENDERER ADAPTER HELPERS
# ============================================================
# These helpers are intentionally kept in the same file so the crop renderer
# can import one module only. They do not run face detection; they only normalize
# crop_plan data produced by main_analyzer().

@dataclass(frozen=True)
class RenderSegment:
    start_time: float
    end_time: float
    layout: str
    layout_variant: str
    pan: float
    split_orientation: Optional[str]
    subjects: List[Dict[str, Any]]
    raw: Dict[str, Any]

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    @property
    def is_split_left_right(self) -> bool:
        return (
            self.layout == LAYOUT_SPLIT_LEFT_RIGHT
            or self.layout_variant == VARIANT_DUAL_SPLIT_LR
            or self.split_orientation == "left_right"
        )

    @property
    def is_wide_center(self) -> bool:
        return (
            self.layout == LAYOUT_WIDE_CONTEXT
            and self.layout_variant == VARIANT_WIDE_CENTER
        )


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_layout(segment: Dict[str, Any]) -> str:
    """Return real layout instead of legacy compatibility label."""
    layout = str(segment.get("layout") or LAYOUT_WIDE_CONTEXT)
    variant = str(segment.get("layout_variant") or "")
    orientation = segment.get("split_orientation")
    visual_orientation = segment.get("visual_split_orientation")

    if visual_orientation == "top_bottom":
        return LAYOUT_SPLIT_TOP_BOTTOM

    if visual_orientation == "left_right":
        return LAYOUT_SPLIT_LEFT_RIGHT

    if layout == LAYOUT_SPLIT_TOP_BOTTOM or orientation == "top_bottom":
        return LAYOUT_SPLIT_TOP_BOTTOM

    if variant == VARIANT_DUAL_SPLIT_LR or orientation == "left_right":
        return LAYOUT_SPLIT_LEFT_RIGHT

    if variant == VARIANT_DUAL_SPLIT_TB or orientation == "top_bottom":
        return LAYOUT_SPLIT_TOP_BOTTOM

    if layout == LAYOUT_SPLIT_TOP_BOTTOM and orientation == "left_right":
        return LAYOUT_SPLIT_LEFT_RIGHT

    return layout


def resolve_render_segments(crop_plan: Dict[str, Any]) -> List[RenderSegment]:
    """Resolve dynamic segments if present; otherwise return one static segment."""
    raw_segments = crop_plan.get("segments") or crop_plan.get("dynamic_segments")

    if not raw_segments:
        raw_segments = [crop_plan]

    resolved: List[RenderSegment] = []

    for raw in raw_segments:
        start = _to_float(
            raw.get("start_time", raw.get("clip_start", crop_plan.get("start_time", 0.0)))
        )
        end = _to_float(
            raw.get("end_time", raw.get("clip_end", crop_plan.get("end_time", start)))
        )
        layout_variant = str(raw.get("layout_variant") or VARIANT_WIDE_CENTER)
        layout = normalize_layout(raw)
        pan = _to_float(raw.get("pan"), BASELINE_WIDE_CENTER_PAN)

        resolved.append(
            RenderSegment(
                start_time=start,
                end_time=end,
                layout=layout,
                layout_variant=layout_variant,
                pan=clamp(pan),
                split_orientation=raw.get("split_orientation"),
                subjects=list(raw.get("subjects") or []),
                raw=raw,
            )
        )

    resolved.sort(key=lambda item: (item.start_time, item.end_time))
    return [item for item in resolved if item.duration > 0.01]


def get_left_right_subjects(segment: RenderSegment) -> Dict[str, Optional[Dict[str, Any]]]:
    """Pick left/right subjects for split-left-right renderer."""
    subjects = sorted(
        segment.subjects,
        key=lambda item: _to_float(item.get("pan"), BASELINE_WIDE_CENTER_PAN),
    )

    if len(subjects) >= 2:
        return {"left": subjects[0], "right": subjects[-1]}

    return {"left": subjects[0] if subjects else None, "right": None}


def build_renderer_debug_summary(crop_plan: Dict[str, Any]) -> Dict[str, Any]:
    segments = resolve_render_segments(crop_plan)
    return {
        "layout_mode": crop_plan.get("layout_mode", "static"),
        "segment_count": len(segments),
        "has_dynamic_segments": bool(
            crop_plan.get("segments") or crop_plan.get("dynamic_segments")
        ),
        "has_split_left_right": any(segment.is_split_left_right for segment in segments),
        "segments": [
            {
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "duration": round(segment.duration, 3),
                "layout": segment.layout,
                "layout_variant": segment.layout_variant,
                "pan": segment.pan,
                "split_orientation": segment.split_orientation,
                "render_mode": (segment.raw.get("frame_position") or {}).get("render_mode"),
                "adaptive_zoom": _to_float(
                    (segment.raw.get("frame_position") or {}).get("zoom"),
                    1.0,
                ),
                "angle_confidence": _to_float(
                    (segment.raw.get("angle_evidence") or {}).get("angle_confidence"),
                    0.0,
                ),
                "angle_rejection_reason": (
                    segment.raw.get("angle_evidence") or {}
                ).get("rejection_reason"),
                "subject_count": len(segment.subjects),
                "frame_position_safe": bool(
                    (segment.raw.get("frame_position") or {}).get("safe", True)
                ),
                "cut_risk_score": _to_float(
                    (segment.raw.get("frame_position") or {}).get("cut_risk_score"),
                    0.0,
                ),
            }
            for segment in segments
        ],
    }


def extract_clip_plans_from_crop_plan_document(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Accept either full crop_plan.json or one clip crop_plan."""
    clips = document.get("clips")
    if isinstance(clips, list):
        return [clip for clip in clips if isinstance(clip, dict)]
    return [document]


def main_renderer_adapter_debug() -> None:
    """
    Debug/inspection entrypoint for renderer integration.

    Usage:
      python visual_layout_analyzer_combined.py adapter-debug <crop_plan.json>

    It prints normalized render segments, proving whether renderer should use
    dynamic segments or fallback static mode.
    """
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: visual_layout_analyzer_combined.py adapter-debug <crop_plan.json>"
        )

    crop_plan_path = Path(sys.argv[2])
    document = json.loads(crop_plan_path.read_text(encoding="utf-8"))
    clip_plans = extract_clip_plans_from_crop_plan_document(document)

    output = {
        "source": str(crop_plan_path),
        "clip_count": len(clip_plans),
        "clips": [
            {
                "clip_index": clip.get("clip_index", index + 1),
                **build_renderer_debug_summary(clip),
            }
            for index, clip in enumerate(clip_plans)
        ],
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


def main() -> None:
    """
    Dispatcher with two entrypoints in one file.

    Analyzer mode, compatible with previous CLI:
      python visual_layout_analyzer_combined.py <result.json> <video_file> <run_dir>

    Adapter debug mode:
      python visual_layout_analyzer_combined.py adapter-debug <crop_plan.json>
    """
    if len(sys.argv) >= 2 and sys.argv[1] == "adapter-debug":
        main_renderer_adapter_debug()
        return

    main_analyzer()


if __name__ == "__main__":
    main()
