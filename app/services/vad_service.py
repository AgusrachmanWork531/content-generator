import logging
import subprocess
import tempfile
import os
import numpy as np
from typing import List, Dict

logger = logging.getLogger(__name__)

_vad_model = None
_vad_available = False

try:
    from silero_vad_lite import SileroVAD
    _vad_available = True
except ImportError:
    logger.warning("silero-vad-lite not installed. VAD features will be disabled.")

def _get_vad_model():
    global _vad_model
    if _vad_model is None and _vad_available:
        try:
            _vad_model = SileroVAD(sample_rate=16000)
            logger.info(f"🚀 Silero VAD Engine Loaded. Methods: {dir(_vad_model)}")
        except Exception as e:
            logger.error(f"Failed to init SileroVAD: {e}")
    return _vad_model

def get_speech_timestamps(video_path: str, sample_rate: int = 16000, 
                          threshold: float = 0.5, 
                          min_speech_duration_ms: int = 200, 
                          min_silence_duration_ms: int = 300) -> List[Dict]:
    model = _get_vad_model()
    if model is None: return []

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            "ffmpeg", "-y", "-i", video_path, 
            "-ar", str(sample_rate), "-ac", "1", "-f", "wav", 
            "-loglevel", "error", tmp_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        import wave
        with wave.open(tmp_path, "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames == 0: return []
            frames = wf.readframes(n_frames)
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

        window_size = 512
        speech_probs = []
        
        if hasattr(model, 'reset_states'):
            model.reset_states()

        # Deteksi metode inferensi yang tersedia di silero-vad-lite
        infer_method = None
        if hasattr(model, 'process'):
            infer_method = model.process
        elif hasattr(model, 'predict'):
            infer_method = model.predict
        elif hasattr(model, 'get_speech_prob'):
            infer_method = model.get_speech_prob
        elif callable(model):
            infer_method = model
        
        if not infer_method:
            logger.error(f"Could not find any inference method in SileroVAD. Dir: {dir(model)}")
            return []

        logger.info(f"Using VAD inference method: {infer_method.__name__ if hasattr(infer_method, '__name__') else 'callable'}")

        for i in range(0, len(audio), window_size):
            chunk = audio[i:i + window_size]
            if len(chunk) < window_size:
                chunk = np.pad(chunk, (0, window_size - len(chunk)), mode='constant')
            
            try:
                # Call detected method
                prob = infer_method(chunk)
                if isinstance(prob, dict):
                    p = prob.get('speech', 0.0)
                else:
                    p = float(prob)
                speech_probs.append(p)
            except Exception as e:
                if i == 0: # Only log first failure to avoid spam
                    logger.warning(f"Frame inference error: {e}")
                speech_probs.append(0.0)

        # Post-processing (sama seperti sebelumnya)
        speech_mask = np.array(speech_probs) > threshold
        min_speech_steps = int((min_speech_duration_ms / 1000) * sample_rate / window_size)
        min_silence_steps = int((min_silence_duration_ms / 1000) * sample_rate / window_size)

        # Merge short silence gaps
        smoothed_mask = speech_mask.copy()
        silence_start = -1
        for i, val in enumerate(smoothed_mask):
            if not val:
                if silence_start == -1: silence_start = i
            else:
                if silence_start != -1:
                    if (i - silence_start) < min_silence_steps:
                        smoothed_mask[silence_start:i] = True
                    silence_start = -1

        # Remove short noise bursts
        final_mask = smoothed_mask.copy()
        speech_start = -1
        for i, val in enumerate(final_mask):
            if val:
                if speech_start == -1: speech_start = i
            else:
                if speech_start != -1:
                    if (i - speech_start) < min_speech_steps:
                        final_mask[speech_start:i] = False
                    speech_start = -1

        segments = []
        start_step = -1
        for i, val in enumerate(final_mask):
            if val and start_step == -1:
                start_step = i
            elif not val and start_step != -1:
                segments.append({
                    "start": (start_step * window_size) / sample_rate,
                    "end": (i * window_size) / sample_rate
                })
                start_step = -1
        
        if start_step != -1:
            segments.append({
                "start": (start_step * window_size) / sample_rate,
                "end": (len(final_mask) * window_size) / sample_rate
            })

        logger.info(f"VAD: Detected {len(segments)} refined speech segments.")
        return segments

    except Exception as e:
        logger.error(f"VAD Pipeline Exception: {e}")
        return []
    finally:
        if os.path.exists(tmp_path): os.unlink(tmp_path)

def build_speech_timeline(video_path: str, step_sec: float = 0.1, duration: float = None) -> np.ndarray:
    segments = get_speech_timestamps(video_path)
    if not segments:
        return np.zeros(int(duration/step_sec) if duration else 100, dtype=np.float32)

    if not duration:
        duration = max([s["end"] for s in segments]) + 1.0
    
    steps = int(duration / step_sec)
    timeline = np.zeros(steps, dtype=np.float32)
    for s in segments:
        start_idx = int(s["start"] / step_sec)
        end_idx = int(s["end"] / step_sec) + 1
        timeline[max(0, start_idx):min(steps, end_idx)] = 1.0
    return timeline

def compute_turn_taking_score(speech_timeline: np.ndarray, window_steps: int = 30) -> np.ndarray:
    if len(speech_timeline) < window_steps: return np.zeros_like(speech_timeline)
    scores = np.zeros_like(speech_timeline)
    for i in range(len(speech_timeline)):
        start = max(0, i - window_steps // 2)
        end = min(len(speech_timeline), i + window_steps // 2)
        seg = speech_timeline[start:end]
        if len(seg) < 3: continue
        transitions = np.sum(np.abs(np.diff(seg)))
        scores[i] = min(1.0, transitions / (window_steps * 0.4))
    return scores
