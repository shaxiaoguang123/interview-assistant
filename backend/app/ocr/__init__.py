from __future__ import annotations

from threading import Lock

from flask import Flask
from PIL import Image

from .adapter import OCRAdapter, OCRAdapterInitializationError, OCRDetection


_APP_EXTENSION_LOCK_GUARD = Lock()


def _app_lock(app: Flask, name: str) -> Lock:
    with _APP_EXTENSION_LOCK_GUARD:
        lock = app.extensions.get(name)
        if lock is None:
            lock = Lock()
            app.extensions[name] = lock
        return lock


def get_ocr_adapter(app: Flask) -> OCRAdapter:
    with _app_lock(app, "ocr_adapter_init_lock"):
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


def recognize_with_ocr_adapter(
    app: Flask,
    adapter: OCRAdapter,
    image: Image.Image,
) -> list[OCRDetection]:
    # RapidOCR/ONNX sessions are shared within one Flask process. Serialize inference
    # without holding a lock around any per-job database work or state transition.
    with _app_lock(app, "ocr_inference_lock"):
        return adapter.recognize(image)


__all__ = [
    "OCRAdapter",
    "OCRAdapterInitializationError",
    "OCRDetection",
    "get_ocr_adapter",
    "recognize_with_ocr_adapter",
]
