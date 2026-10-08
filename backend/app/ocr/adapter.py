from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol
from uuid import UUID

from PIL import Image


class OCRAdapterInitializationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OCRDetection:
    id: str
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None
    reading_order: int
    block_type: str = "text"

    def __post_init__(self) -> None:
        UUID(self.id)
        if len(self.bbox) != 4:
            raise ValueError("bbox must contain x, y, width, and height")
        x, y, width, height = self.bbox
        if not all(math.isfinite(value) for value in self.bbox):
            raise ValueError("bbox values must be finite")
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x > 1
            or y > 1
            or width > 1
            or height > 1
            or x + width > 1
            or y + height > 1
        ):
            raise ValueError("bbox must fit within normalized image coordinates")
        if self.confidence is not None and (
            not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be a finite value from 0 to 1")
        if self.reading_order < 0:
            raise ValueError("reading_order cannot be negative")


class OCRAdapter(Protocol):
    name: str
    version: str

    def recognize(self, image: Image.Image) -> list[OCRDetection]:
        ...
