from __future__ import annotations

from hashlib import sha256
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from .adapter import OCRAdapterInitializationError, OCRDetection


_PINNED_FILES = {
    "det": (
        "PP-OCRv6_det_small.onnx",
        "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    ),
    "rec": (
        "PP-OCRv6_rec_small.onnx",
        "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    ),
    "cls": (
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    ),
}
_CONFIG_PATHS = {
    "det": "OCR_DETECTION_MODEL_PATH",
    "rec": "OCR_RECOGNITION_MODEL_PATH",
    "cls": "OCR_CLASSIFICATION_MODEL_PATH",
}


def detections_from_output(
    output: Any, *, image_width: int, image_height: int
) -> list[OCRDetection]:
    boxes = getattr(output, "boxes", None)
    texts = getattr(output, "txts", None)
    scores = getattr(output, "scores", None)
    if boxes is None or texts is None or scores is None:
        return []

    detections: list[OCRDetection] = []
    for reading_order, (box, text, score) in enumerate(zip(boxes, texts, scores)):
        points = [(float(point[0]), float(point[1])) for point in box]
        if len(points) < 4:
            continue
        left = max(0.0, min(point[0] for point in points))
        top = max(0.0, min(point[1] for point in points))
        right = min(float(image_width), max(point[0] for point in points))
        bottom = min(float(image_height), max(point[1] for point in points))
        if right <= left or bottom <= top:
            continue

        x = left / image_width
        y = top / image_height
        width = min((right - left) / image_width, 1.0 - x)
        height = min((bottom - top) / image_height, 1.0 - y)
        confidence = float(score) if score is not None else None
        if confidence is not None and not math.isfinite(confidence):
            confidence = None
        detections.append(
            OCRDetection(
                id=str(uuid4()),
                text=str(text),
                bbox=(x, y, width, height),
                confidence=confidence,
                reading_order=reading_order,
                block_type="text",
            )
        )
    return detections


def _model_paths(config: dict) -> tuple[Path, dict[str, Path], dict[str, str]]:
    model_root = Path(config["OCR_MODEL_DIR"]).expanduser().resolve()
    manifest_path = Path(
        config.get("OCR_MODEL_MANIFEST_PATH") or model_root / "manifest.json"
    ).expanduser()
    if not manifest_path.is_absolute():
        manifest_path = model_root / manifest_path
    manifest_path = manifest_path.resolve()
    if model_root != manifest_path.parent and model_root not in manifest_path.parents:
        raise OCRAdapterInitializationError(
            "OCR_MODEL_INVALID", "OCR model manifest must be inside OCR_MODEL_DIR"
        )
    if not manifest_path.is_file():
        raise OCRAdapterInitializationError(
            "OCR_MODEL_MISSING", "Local OCR model manifest is missing"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise OCRAdapterInitializationError(
            "OCR_MODEL_INVALID", "Local OCR model manifest is invalid"
        ) from error

    if (
        not isinstance(manifest, dict)
        or manifest.get("model_release") != "PP-OCRv6-small"
        or manifest.get("rapidocr_version") != config["OCR_RAPIDOCR_VERSION"]
        or manifest.get("onnxruntime_version") != config["OCR_ONNXRUNTIME_VERSION"]
        or not isinstance(manifest.get("files"), dict)
    ):
        raise OCRAdapterInitializationError(
            "OCR_MODEL_INVALID", "Local OCR model manifest version is invalid"
        )

    model_paths: dict[str, Path] = {}
    model_digests: dict[str, str] = {}
    for role, (expected_name, expected_digest) in _PINNED_FILES.items():
        entry = manifest["files"].get(role)
        if not isinstance(entry, dict):
            raise OCRAdapterInitializationError(
                "OCR_MODEL_INVALID", "Local OCR model manifest is incomplete"
            )
        configured_path = config.get(_CONFIG_PATHS[role])
        model_path = Path(configured_path or model_root / expected_name).expanduser()
        if not model_path.is_absolute():
            model_path = model_root / model_path
        model_path = model_path.resolve()
        if model_root not in model_path.parents:
            raise OCRAdapterInitializationError(
                "OCR_MODEL_INVALID", "OCR model paths must remain inside OCR_MODEL_DIR"
            )
        if not model_path.is_file():
            raise OCRAdapterInitializationError(
                "OCR_MODEL_MISSING", "A required local OCR model file is missing"
            )
        if entry.get("filename") != model_path.name or entry.get("filename") != expected_name:
            raise OCRAdapterInitializationError(
                "OCR_MODEL_INVALID", "Local OCR model filename does not match the pinned release"
            )
        actual_digest = sha256(model_path.read_bytes()).hexdigest()
        if entry.get("sha256") != expected_digest or actual_digest != expected_digest:
            raise OCRAdapterInitializationError(
                "OCR_MODEL_INVALID", "Local OCR model checksum does not match the pinned release"
            )
        model_paths[role] = model_path
        model_digests[role] = actual_digest
    return manifest_path, model_paths, model_digests


class RapidOCRAdapter:
    name = "rapidocr-onnxruntime"
    provider = "CPUExecutionProvider"

    @classmethod
    def from_config(cls, config: dict) -> "RapidOCRAdapter":
        return cls(config)

    def __init__(self, config: dict) -> None:
        if config.get("OCR_ENGINE", "rapidocr_onnx") != "rapidocr_onnx":
            raise OCRAdapterInitializationError(
                "OCR_RUNTIME_UNAVAILABLE", "Configured OCR engine is unsupported"
            )
        self.model_root = Path(config["OCR_MODEL_DIR"]).expanduser().resolve()
        manifest_path, model_paths, model_digests = _model_paths(config)
        expected_rapidocr = str(config["OCR_RAPIDOCR_VERSION"])
        expected_onnxruntime = str(config["OCR_ONNXRUNTIME_VERSION"])
        try:
            rapidocr_version = importlib.metadata.version("rapidocr")
            onnxruntime_version = importlib.metadata.version("onnxruntime")
        except importlib.metadata.PackageNotFoundError as error:
            raise OCRAdapterInitializationError(
                "OCR_RUNTIME_UNAVAILABLE", "Pinned OCR runtime packages are not installed"
            ) from error
        if (
            rapidocr_version != expected_rapidocr
            or onnxruntime_version != expected_onnxruntime
        ):
            raise OCRAdapterInitializationError(
                "OCR_RUNTIME_UNAVAILABLE",
                "Installed OCR runtime versions do not match the tested pins",
            )

        try:
            from rapidocr import RapidOCR

            self._engine = RapidOCR(
                params={
                    "Global.model_root_dir": str(self.model_root),
                    "Global.log_level": "warning",
                    "EngineConfig.onnxruntime.use_cuda": False,
                    "EngineConfig.onnxruntime.use_coreml": False,
                    "EngineConfig.onnxruntime.use_dml": False,
                    "EngineConfig.onnxruntime.use_cann": False,
                    "Det.model_path": str(model_paths["det"]),
                    "Cls.model_path": str(model_paths["cls"]),
                    "Rec.model_path": str(model_paths["rec"]),
                }
            )
            self._verify_cpu_providers()
        except OCRAdapterInitializationError:
            raise
        except Exception as error:
            raise OCRAdapterInitializationError(
                "OCR_RUNTIME_UNAVAILABLE", "Could not initialize the local CPU OCR runtime"
            ) from error

        self.runtime_version = (
            f"rapidocr={rapidocr_version};onnxruntime={onnxruntime_version}"
        )
        self.model_release = "PP-OCRv6-small"
        self.model_digest_summary = ",".join(
            f"{role}:{digest}" for role, digest in sorted(model_digests.items())
        )
        self.version = (
            f"{self.runtime_version};model={self.model_release};"
            f"provider={self.provider};sha256={self.model_digest_summary}"
        )
        self.manifest_path = manifest_path

    def _verify_cpu_providers(self) -> None:
        for component_name in ("text_det", "text_cls", "text_rec"):
            component = getattr(self._engine, component_name, None)
            infer_session = getattr(component, "session", None)
            ort_session = getattr(infer_session, "session", None)
            if ort_session is None or not callable(
                getattr(ort_session, "get_providers", None)
            ):
                raise OCRAdapterInitializationError(
                    "OCR_RUNTIME_UNAVAILABLE", "OCR component is not using ONNX Runtime"
                )
            if ort_session.get_providers() != [self.provider]:
                raise OCRAdapterInitializationError(
                    "OCR_RUNTIME_UNAVAILABLE",
                    "OCR runtime is not using CPUExecutionProvider only",
                )

    def recognize(self, image: Image.Image) -> list[OCRDetection]:
        rgb_image = image.convert("RGB")
        output = self._engine(rgb_image)
        return detections_from_output(
            output,
            image_width=rgb_image.width,
            image_height=rgb_image.height,
        )
