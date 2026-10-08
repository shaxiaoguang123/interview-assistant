from __future__ import annotations

from flask import Flask

from .adapter import OCRAdapter, OCRAdapterInitializationError, OCRDetection


def get_ocr_adapter(app: Flask) -> OCRAdapter:
    cached = app.extensions.get("ocr_adapter")
    if cached is not None:
        return cached

    factory = app.config.get("OCR_ADAPTER_FACTORY")
    if factory is not None:
        adapter = factory()
    else:
        # Keep the optional OCR runtime out of Flask's ordinary app startup path.
        from .rapidocr_adapter import RapidOCRAdapter

        adapter = RapidOCRAdapter.from_config(app.config)

    if not callable(getattr(adapter, "recognize", None)):
        raise OCRAdapterInitializationError(
            "OCR_RUNTIME_UNAVAILABLE", "Configured OCR adapter is invalid"
        )
    app.extensions["ocr_adapter"] = adapter
    return adapter


__all__ = [
    "OCRAdapter",
    "OCRAdapterInitializationError",
    "OCRDetection",
    "get_ocr_adapter",
]
