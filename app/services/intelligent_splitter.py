import cv2
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from app.services.audio_analyzer import get_audio_energy_map


@dataclass
class ClipSegment:
    start: float
    end: float
    score: float


class IntelligentSplitter:
    """Multimodal splitter with CPD-like peak proposal + duration constraints."""

    def __init__(self, step_sec: float = 0.1):
        self.step_sec = step_sec
        self.min_len = 15.0
        self.max_len = 60.0
        self.min_gap = 8.0

    @staticmethod
    def _z(x: np.ndarray) -> np.ndarray:
        med = np.median(x)
        mad = np.median(np.abs(x - med)) + 1e-6
        return (x - med) / (1.4826 * mad)

    def _visual_activity(self, video_path: str, target_steps: int) -> np.ndarray:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        interval = max(1, int(round(fps * self.step_sec)))
        prev = None
        scores = []
        idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % interval == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if prev is None:
                    scores.append(0.0)
                else:
                    diff = cv2.absdiff(gray, prev)
                    scores.append(float(np.mean(diff) / 255.0))
                prev = gray
            idx += 1
        cap.release()
        if not scores:
            scores = [0.0] * target_steps
        arr = np.array(scores, dtype=np.float32)
        if len(arr) < target_steps:
            arr = np.pad(arr, (0, target_steps - len(arr)), mode="edge")
        return arr[:target_steps]

    def _transcript_importance(self, transcript: Optional[List[Dict]], target_steps: int) -> np.ndarray:
        out = np.zeros(target_steps, dtype=np.float32)
        if not transcript:
            return out
        viral_keywords = {"rahasia", "ternyata", "gila", "wajib", "tips", "cara", "penting", "viral", "stop", "jangan"}
        for row in transcript:
            text = str(row.get("text", "")).lower()
            start = float(row.get("start", 0.0))
            dur = float(row.get("duration", 0.0))
            end = start + max(0.5, dur)
            score = 0.0
            for k in viral_keywords:
                if k in text:
                    score += 1.0
            score += min(1.0, len(text.split()) / 16.0)
            s = int(start / self.step_sec)
            e = int(end / self.step_sec) + 1
            out[max(0, s):min(target_steps, e)] = np.maximum(out[max(0, s):min(target_steps, e)], score)
        return out

    def find_best_segment(self, video_path: str, transcript: Optional[List[Dict]] = None) -> ClipSegment:
        energy = np.array(get_audio_energy_map(video_path), dtype=np.float32)
        if len(energy) == 0:
            return ClipSegment(0.0, 30.0, 0.0)

        # audio map uses 0.1s bins in current codebase
        target_steps = len(energy)
        visual = self._visual_activity(video_path, target_steps)
        text = self._transcript_importance(transcript, target_steps)

        # Speech timeline from Silero VAD (falls back to energy proxy if unavailable)
        try:
            from app.services.vad_service import build_speech_timeline
            speech = build_speech_timeline(video_path, step_sec=self.step_sec, duration=target_steps * self.step_sec)
            if len(speech) < target_steps:
                speech = np.pad(speech, (0, target_steps - len(speech)), mode="edge")
            speech = speech[:target_steps]
        except Exception:
            speech = (energy > np.percentile(energy, 45)).astype(np.float32)

        context_shift = np.abs(np.diff(text, prepend=text[0]))

        # Use CPD-enhanced importance scoring if available
        try:
            from app.services.cpd_service import build_importance_score
            score = build_importance_score(energy, speech, visual, text)
        except Exception:
            score = (
                0.22 * self._z(energy)
                + 0.18 * self._z(speech)
                + 0.30 * self._z(text + 1e-3)
                + 0.20 * self._z(visual + 1e-3)
                + 0.10 * self._z(context_shift + 1e-3)
            )

        win = int(self.max_len / self.step_sec)
        min_win = int(self.min_len / self.step_sec)
        csum = np.concatenate([[0.0], np.cumsum(score)])

        best = (-1e18, 0, min_win)
        for s in range(0, max(1, target_steps - min_win)):
            e_hi = min(target_steps, s + win)
            e_lo = s + min_win
            if e_lo >= e_hi:
                continue
            for e in (e_lo, min(e_hi, e_lo + int(15 / self.step_sec)), e_hi):
                val = (csum[e] - csum[s]) / max(1, e - s)
                hook = np.max(score[s:min(e, s + int(5 / self.step_sec))])
                payoff = np.max(score[max(s, e - int(5 / self.step_sec)):e])
                total = float(val + 0.15 * hook + 0.1 * payoff)
                if total > best[0]:
                    best = (total, s, e)

        start = best[1] * self.step_sec
        end = best[2] * self.step_sec
        return ClipSegment(start=start, end=end, score=float(best[0]))
