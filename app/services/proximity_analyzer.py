import logging

logger = logging.getLogger(__name__)

class ProximityAnalyzer:
    def __init__(self, base_proximity: float = 0.5):
        self.base_proximity = base_proximity
        
    def analyze(self, boxes: list) -> float:
        """
        Analyzes subject proximity based on bounding boxes.
        Returns a factor to adjust zoom/crop.
        """
        if not boxes:
            return self.base_proximity
            
        # Simplified logic for now: use the largest box's relative width
        max_width = 0
        for box in boxes:
            w = box[2] - box[0]
            if w > max_width:
                max_width = w
                
        return max_width / 1080.0 # Normalized to 1080p
