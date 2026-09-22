import pytest

from app.config import Settings


def test_camera_backend_defaults_to_fswebcam(monkeypatch) -> None:
    monkeypatch.delenv("CAMERA_BACKEND", raising=False)

    assert Settings.from_environment().camera_backend == "fswebcam"


def test_camera_backend_accepts_mock(monkeypatch) -> None:
    monkeypatch.setenv("CAMERA_BACKEND", "mock")

    assert Settings.from_environment().camera_backend == "mock"


def test_camera_backend_accepts_rpicam(monkeypatch) -> None:
    monkeypatch.setenv("CAMERA_BACKEND", "rpicam")
    monkeypatch.delenv("CAMERA_COMMAND", raising=False)

    settings = Settings.from_environment()

    assert settings.camera_backend == "rpicam"
    assert settings.camera_command == "rpicam-still"


def test_camera_backend_accepts_picamera2(monkeypatch) -> None:
    monkeypatch.setenv("CAMERA_BACKEND", "picamera2")

    settings = Settings.from_environment()

    assert settings.camera_backend == "picamera2"
    assert settings.camera_command == "picamera2"


def test_camera_backend_rejects_unknown_value(monkeypatch) -> None:
    monkeypatch.setenv("CAMERA_BACKEND", "other")

    with pytest.raises(ValueError, match="CAMERA_BACKEND"):
        Settings.from_environment()
