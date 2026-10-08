from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import socket
import sys
import time

from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Config
from app.ocr.rapidocr_adapter import RapidOCRAdapter


def _block_network(*_args, **_kwargs):
    raise RuntimeError("network access is disabled during the OCR CPU smoke test")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local offline RapidOCR CPU smoke test.")
    parser.add_argument("--offline", action="store_true", help="block Python socket connections")
    parser.add_argument("image", type=Path, help="path to an already-local image")
    args = parser.parse_args()

    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        socket.socket.connect = _block_network
        socket.socket.connect_ex = _block_network
        socket.create_connection = _block_network

    config_names = (
        "OCR_ENGINE",
        "OCR_RAPIDOCR_VERSION",
        "OCR_ONNXRUNTIME_VERSION",
        "OCR_MODEL_DIR",
        "OCR_MODEL_MANIFEST_PATH",
        "OCR_DETECTION_MODEL_PATH",
        "OCR_RECOGNITION_MODEL_PATH",
        "OCR_CLASSIFICATION_MODEL_PATH",
    )
    config = {name: getattr(Config, name) for name in config_names}
    adapter = RapidOCRAdapter.from_config(config)

    started_at = time.perf_counter()
    with Image.open(args.image) as image:
        image.load()
        detections = adapter.recognize(image)
    elapsed = time.perf_counter() - started_at

    if adapter.provider != "CPUExecutionProvider":
        raise RuntimeError("OCR smoke did not run with CPUExecutionProvider")
    print(f"python={platform.python_version()}")
    print(f"macos={platform.mac_ver()[0] or 'not-macos'}")
    print(f"architecture={platform.machine()}")
    print(f"adapter={adapter.name}")
    print(f"runtime={adapter.runtime_version}")
    print(f"provider={adapter.provider}")
    print(f"model_release={adapter.model_release}")
    print(f"model_sha256={adapter.model_digest_summary}")
    print(f"ocr_blocks={len(detections)}")
    print(f"elapsed_seconds={elapsed:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
