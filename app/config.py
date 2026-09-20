from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CameraBackend = Literal["fswebcam", "mock"]


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc

    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _camera_backend() -> CameraBackend:
    value = os.getenv("CAMERA_BACKEND", "fswebcam")
    if value == "fswebcam" or value == "mock":
        return value
    raise ValueError("CAMERA_BACKEND must be either 'fswebcam' or 'mock'")


@dataclass(frozen=True)
class Settings:
    photo_dir: Path
    camera_backend: CameraBackend
    camera_command: str
    camera_device: str
    camera_width: int
    camera_height: int
    capture_timeout_seconds: int
    minimum_capture_interval_seconds: int
    maximum_photos: int

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            photo_dir=Path(os.getenv("PHOTO_DIR", PROJECT_ROOT / "data" / "photos")),
            camera_backend=_camera_backend(),
            camera_command=os.getenv("CAMERA_COMMAND", "fswebcam"),
            camera_device=os.getenv("CAMERA_DEVICE", "/dev/video0"),
            camera_width=_positive_int("CAMERA_WIDTH", 1280),
            camera_height=_positive_int("CAMERA_HEIGHT", 720),
            capture_timeout_seconds=_positive_int("CAPTURE_TIMEOUT_SECONDS", 15),
            minimum_capture_interval_seconds=_positive_int(
                "MINIMUM_CAPTURE_INTERVAL_SECONDS", 5
            ),
            maximum_photos=_positive_int("MAXIMUM_PHOTOS", 100),
        )
