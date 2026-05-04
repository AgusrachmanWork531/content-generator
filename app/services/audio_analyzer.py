import subprocess
import numpy as np
import logging

logger = logging.getLogger(__name__)

def get_audio_energy_map(video_path: str, chunk_duration: float = 0.1) -> np.ndarray:
    """
    Extracts RMS energy from audio stream of a video file.
    Returns an array of energy levels at chunk_duration intervals.
    """
    try:
        # Extract raw audio as PCM 16-bit mono 16kHz
        cmd = [
            'ffmpeg', '-i', video_path,
            '-f', 's16le', '-ac', '1', '-ar', '16000',
            '-'
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        audio_data, _ = process.communicate()
        
        # Convert to numpy array
        samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        if len(samples) == 0:
            return np.array([])
            
        # Normalize
        samples /= 32768.0
        
        # Calculate RMS in chunks
        chunk_size = int(16000 * chunk_duration)
        num_chunks = len(samples) // chunk_size
        
        if num_chunks == 0:
            return np.array([np.sqrt(np.mean(samples**2))])
            
        energy_map = []
        for i in range(num_chunks):
            chunk = samples[i * chunk_size : (i + 1) * chunk_size]
            rms = np.sqrt(np.mean(chunk**2))
            energy_map.append(rms)
            
        return np.array(energy_map)
    except Exception as e:
        logger.error(f"Error extracting audio energy: {e}")
        return np.array([])
