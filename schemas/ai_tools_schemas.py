from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List




class EmotionDetector(ABC):
    """Abstract base class for emotion detection."""

    @abstractmethod
    def analyze(self, text: str):
        """Analyze the emotion in the given text and return a structured result."""
        pass


@dataclass
class EmotionResult:
    """Structured output for detected emotions."""
    dominant_emotion: str
    confidence: float
    all_scores: Dict[str, float]

