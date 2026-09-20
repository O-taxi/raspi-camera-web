import pytest

from app.config import Settings


def test_camera_backend_defaults_to_fswebcam(monkeypatch) -> None:
    monkeypatch.delenv("CAMERA_BACKEND", raising=False)

    assert Settings.from_environment().camera_backend == "fswebcam"


def test_camera_backend_accepts_mock(monkeypatch) -> None:
    monkeypatch.setenv("CAMERA_BACKEND", "mock")

    assert Settings.from_environment().camera_backend == "mock"


def test_camera_backend_rejects_unknown_value(monkeypatch) -> None:
    monkeypatch.setenv("CAMERA_BACKEND", "other")

    with pytest.raises(ValueError, match="CAMERA_BACKEND"):
        Settings.from_environment()
