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


def test_motion_configuration_reads_boolean_and_validates_recording_limit(monkeypatch) -> None:
    monkeypatch.setenv("MOTION_ENABLED", "false")
    monkeypatch.setenv("MOTION_RECORD_SECONDS", "30")
    monkeypatch.setenv("MOTION_MAX_RECORD_SECONDS", "60")

    settings = Settings.from_environment()

    assert not settings.motion_enabled
    assert settings.motion_analysis_tile_size == 32
    assert settings.motion_min_changed_ratio == 0.10
    assert settings.motion_max_record_seconds == 60

    monkeypatch.setenv("MOTION_MAX_RECORD_SECONDS", "20")
    with pytest.raises(ValueError, match="MOTION_MAX_RECORD_SECONDS"):
        Settings.from_environment()


def test_video_storage_limits_are_positive(monkeypatch) -> None:
    monkeypatch.setenv("MAXIMUM_VIDEO_BYTES", "1000000")
    monkeypatch.setenv("MINIMUM_FREE_DISK_BYTES", "500000")
    settings = Settings.from_environment()
    assert settings.maximum_video_bytes == 1_000_000
    assert settings.minimum_free_disk_bytes == 500_000
    monkeypatch.setenv("MAXIMUM_VIDEO_BYTES", "0")
    with pytest.raises(ValueError, match="MAXIMUM_VIDEO_BYTES"):
        Settings.from_environment()
