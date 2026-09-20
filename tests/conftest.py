from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        photo_dir=tmp_path / "photos",
        camera_backend="fswebcam",
        camera_command="fswebcam",
        camera_device="/dev/video0",
        camera_width=640,
        camera_height=480,
        capture_timeout_seconds=1,
        minimum_capture_interval_seconds=1,
        maximum_photos=3,
    )
