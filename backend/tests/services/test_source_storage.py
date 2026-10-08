from importlib import import_module
from pathlib import Path
from io import BytesIO

from PIL import Image, ImageOps
from werkzeug.datastructures import FileStorage


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _storage_service():
    module_path = BACKEND_ROOT / "app" / "services" / "source_storage.py"
    assert module_path.is_file(), "missing feature: local source storage service"
    return import_module("app.services.source_storage")


def _png_bytes(size=(4, 3)):
    image = Image.new("RGB", size, color=(12, 80, 160))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _jpeg_with_orientation(orientation=6):
    image = Image.new("RGB", (8, 4), color=(180, 25, 55))
    exif = Image.Exif()
    exif[274] = orientation
    stream = BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    return stream.getvalue()


def _file_storage(payload, filename="sample.png", content_type="image/png"):
    return FileStorage(
        stream=BytesIO(payload),
        filename=filename,
        content_type=content_type,
    )


def test_upload_preserves_original_bytes_and_sha256(app):
    service = _storage_service()
    original = _png_bytes()
    with app.app_context():
        source = service.save_source_file(
            _file_storage(original),
            app.config["SOURCE_STORAGE_DIR"],
            {},
        )

    stored_path = Path(app.config["SOURCE_STORAGE_DIR"]) / source.original_path
    assert stored_path.read_bytes() == original
    assert source.sha256 == __import__("hashlib").sha256(original).hexdigest()


def test_upload_path_does_not_use_user_filename(app):
    service = _storage_service()
    with app.app_context():
        source = service.save_source_file(
            _file_storage(_png_bytes(), filename="../../outside/important.png"),
            app.config["SOURCE_STORAGE_DIR"],
            {},
        )

    assert ".." not in source.original_path
    assert "important.png" not in source.original_path
    assert not Path(app.config["SOURCE_STORAGE_DIR"]).parent.joinpath(
        "outside", "important.png"
    ).exists()


def test_upload_rejects_extension_and_mime_spoof(app):
    service = _storage_service()
    with app.app_context():
        try:
            service.save_source_file(
                _file_storage(_png_bytes(), filename="screenshot.jpg", content_type="image/jpeg"),
                app.config["SOURCE_STORAGE_DIR"],
                {},
            )
        except Exception as error:
            assert getattr(error, "code", None) == "VALIDATION_ERROR"
        else:
            raise AssertionError("mismatched declared image type must be rejected")


def test_upload_rejects_invalid_image(app):
    service = _storage_service()
    with app.app_context():
        try:
            service.save_source_file(
                _file_storage(b"this is not an image", filename="bad.png"),
                app.config["SOURCE_STORAGE_DIR"],
                {},
            )
        except Exception as error:
            assert getattr(error, "code", None) == "VALIDATION_ERROR"
        else:
            raise AssertionError("invalid image bytes must be rejected")


def test_upload_rejects_image_over_configured_pixel_limit(app):
    service = _storage_service()
    app.config["SOURCE_MAX_DECODED_PIXELS"] = 32
    with app.app_context():
        try:
            service.save_source_file(
                _file_storage(_png_bytes((8, 8))),
                app.config["SOURCE_STORAGE_DIR"],
                {},
            )
        except Exception as error:
            assert getattr(error, "code", None) == "VALIDATION_ERROR"
        else:
            raise AssertionError("image over the decoded pixel limit must be rejected")


def test_upload_creates_exif_normalized_lossless_display_preview(app):
    service = _storage_service()
    original = _jpeg_with_orientation(orientation=6)
    with app.app_context():
        source = service.save_source_file(
            _file_storage(original, filename="rotated.jpg", content_type="image/jpeg"),
            app.config["SOURCE_STORAGE_DIR"],
            {},
        )

    root = Path(app.config["SOURCE_STORAGE_DIR"])
    assert source.original_width == 8
    assert source.original_height == 4
    assert source.display_width == 4
    assert source.display_height == 8
    assert (root / source.original_path).read_bytes() == original
    with Image.open(root / source.display_preview_path) as preview:
        assert preview.format == "PNG"
        assert preview.size == (4, 8)
        assert ImageOps.exif_transpose(preview).size == preview.size


def test_upload_rejects_oversized_file(app):
    service = _storage_service()
    app.config["SOURCE_MAX_FILE_BYTES"] = 4
    with app.app_context():
        try:
            service.save_source_file(
                _file_storage(_png_bytes()),
                app.config["SOURCE_STORAGE_DIR"],
                {},
            )
        except Exception as error:
            assert getattr(error, "code", None) == "VALIDATION_ERROR"
        else:
            raise AssertionError("oversized image must be rejected")


def test_storage_failure_removes_partially_written_original_and_preview(app, monkeypatch):
    service = _storage_service()
    root = Path(app.config["SOURCE_STORAGE_DIR"])
    original_replace = service.os.replace
    replacements = 0

    def fail_second_replace(source, target):
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("simulated preview rename failure")
        return original_replace(source, target)

    monkeypatch.setattr(service.os, "replace", fail_second_replace)
    with app.app_context():
        try:
            service.save_source_file(
                _file_storage(_png_bytes()),
                root,
                {},
            )
        except OSError:
            pass
        else:
            raise AssertionError("simulated filesystem failure must propagate")

    assert not list(root.rglob("*.bin"))
    assert not list(root.rglob("*.png"))
    assert not list(root.rglob("*.tmp"))
