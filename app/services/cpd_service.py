"""
Change Point Detection Service — Detects natural transition points in multimodal timelines.
Uses `ruptures` PELT algorithm for offline, optimal changepoint detection.
Falls back to simple peak-finding if ruptures is not installed.
"""
import logging
import numpy as np

logger = logging.getLogger(__name__)

_ruptures_available = False
try:
    import ruptures as rpt
    _ruptures_available = True
except ImportError:
    logger.warning("ruptures not installed. Falling back to peak-based CPD. Install with: pip install ruptures")


def detect_change_points(
    signal: np.ndarray,
    penalty: float = 10.0,
    min_size: int = 30,
    model: str = "rbf"
) -> list:
    """
    Detect change points in a 1D signal using PELT algorithm.
    Returns list of indices where significant changes occur.
    
    Args:
        signal: 1D numpy array (e.g. importance score timeline)
        penalty: Higher = fewer splits. Range 5-20 typical.
        min_size: Minimum segment length in steps between change points.
        model: Cost model ("rbf", "l2", "l1", "linear")
    """
    if len(signal) < min_size * 2:
        return []

    if _ruptures_available:
        try:
            algo = rpt.Pelt(model=model, min_size=min_size).fit(signal)
            bkps = algo.predict(pen=penalty)
            # Remove the last element (always = len(signal))
            result = [b for b in bkps if b < len(signal)]
            logger.info(f"ruptures PELT detected {len(result)} change points (pen={penalty})")
            return result
        except Exception as e:
            logger.error(f"ruptures PELT failed: {e}")
            return _fallback_peak_cpd(signal, min_size)
    else:
        return _fallback_peak_cpd(signal, min_size)


def _fallback_peak_cpd(signal: np.ndarray, min_size: int = 30) -> list:
    """
    Fallback CPD using derivative peaks when ruptures is unavailable.
    """
    if len(signal) < min_size:
        return []

    # Compute absolute derivative
    deriv = np.abs(np.diff(signal))
    threshold = np.percentile(deriv, 85)

    peaks = []
    last_peak = -min_size
    for i in range(len(deriv)):
        if deriv[i] > threshold and (i - last_peak) >= min_size:
            peaks.append(i)
            last_peak = i

    logger.info(f"Fallback CPD detected {len(peaks)} change points")
    return peaks


def build_importance_score(
    audio_energy: np.ndarray,
    speech_timeline: np.ndarray,
    visual_activity: np.ndarray,
    transcript_importance: np.ndarray = None,
    weights: dict = None
) -> np.ndarray:
    """
    Build unified importance score from multimodal signals.
    All inputs should be same length (aligned to same step grid).
    
    Default weights (Opus-Clip-class):
        audio=0.22, speech=0.18, visual=0.20, nlp=0.30, context_shift=0.10
    """
    if weights is None:
        weights = {
            "audio": 0.22,
            "speech": 0.18,
            "visual": 0.20,
            "nlp": 0.30,
            "context_shift": 0.10
        }

    target_len = len(audio_energy)

    def _align(arr):
        if arr is None:
            return np.zeros(target_len)
        if len(arr) < target_len:
            return np.pad(arr, (0, target_len - len(arr)), mode="edge")
        return arr[:target_len]

    def _robust_z(x):
        med = np.median(x)
        mad = np.median(np.abs(x - med)) + 1e-6
        return (x - med) / (1.4826 * mad)

    audio = _align(audio_energy)
    speech = _align(speech_timeline)
    visual = _align(visual_activity)
    nlp = _align(transcript_importance) if transcript_importance is not None else np.zeros(target_len)

    # Context shift = derivative of NLP importance
    context_shift = np.abs(np.diff(nlp, prepend=nlp[0]))

    score = (
        weights["audio"] * _robust_z(audio + 1e-6)
        + weights["speech"] * _robust_z(speech + 1e-6)
        + weights["visual"] * _robust_z(visual + 1e-6)
        + weights["nlp"] * _robust_z(nlp + 1e-6)
        + weights["context_shift"] * _robust_z(context_shift + 1e-6)
    )

    return score


def find_split_boundaries(
    importance_score: np.ndarray,
    speech_timeline: np.ndarray,
    step_sec: float = 0.1,
    penalty: float = 10.0,
    min_segment_sec: float = 8.0
) -> list:
    """
    Find natural split boundaries using CPD + speech edges.
    Returns list of time points (in seconds) where layout transitions are natural.
    
    Split boundaries prefer:
    1. Change points in importance score (mood/topic change)
    2. Speech edges (silence gaps between speakers)
    3. Minimum distance constraint between boundaries
    """
    min_steps = int(min_segment_sec / step_sec)

    # Get CPD boundaries
    cpd_points = detect_change_points(importance_score, penalty=penalty, min_size=min_steps)

    # Get speech edges (silence→speech or speech→silence transitions)
    speech_edges = []
    if len(speech_timeline) > 1:
        diffs = np.abs(np.diff(speech_timeline))
        edge_indices = np.where(diffs > 0.5)[0]
        speech_edges = edge_indices.tolist()

    # Merge and deduplicate boundaries
    all_boundaries = sorted(set(cpd_points + speech_edges))

    # Enforce minimum distance
    filtered = []
    last = -min_steps
    for b in all_boundaries:
        if b - last >= min_steps:
            filtered.append(b)
            last = b

    # Convert to seconds
    result = [b * step_sec for b in filtered]
    logger.info(f"Found {len(result)} natural split boundaries")
    return result
