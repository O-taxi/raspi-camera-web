from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CameraBackend = Literal["fswebcam", "rpicam", "picamera2", "mock"]


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


def _positive_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc

    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _camera_backend() -> CameraBackend:
    value = os.getenv("CAMERA_BACKEND", "fswebcam")
    if value in ("fswebcam", "rpicam", "picamera2", "mock"):
        return value
    raise ValueError(
        "CAMERA_BACKEND must be 'fswebcam', 'rpicam', 'picamera2', or 'mock'"
    )


def _default_camera_command(camera_backend: CameraBackend) -> str:
    if camera_backend == "rpicam":
        return "rpicam-still"
    if camera_backend == "picamera2":
        return "picamera2"
    return "fswebcam"


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
    camera_capture_delay_ms: int = 1000
    video_dir: Path = PROJECT_ROOT / "data" / "videos"
    maximum_videos: int = 20
    video_width: int = 1280
    video_height: int = 720
    video_fps: int = 15
    video_bitrate: int = 2_000_000
    live_stream_width: int = 640
    live_stream_height: int = 360
    live_stream_fps: int = 5
    motion_threshold: float = 12.0
    motion_minimum_consecutive_frames: int = 3
    motion_record_seconds: int = 20
    motion_cooldown_seconds: int = 30

    @classmethod
    def from_environment(cls) -> Settings:
        camera_backend = _camera_backend()
        return cls(
            photo_dir=Path(os.getenv("PHOTO_DIR", PROJECT_ROOT / "data" / "photos")),
            camera_backend=camera_backend,
            camera_command=os.getenv("CAMERA_COMMAND", _default_camera_command(camera_backend)),
            camera_device=os.getenv("CAMERA_DEVICE", "/dev/video0"),
            camera_width=_positive_int("CAMERA_WIDTH", 1280),
            camera_height=_positive_int("CAMERA_HEIGHT", 720),
            capture_timeout_seconds=_positive_int("CAPTURE_TIMEOUT_SECONDS", 15),
            minimum_capture_interval_seconds=_positive_int(
                "MINIMUM_CAPTURE_INTERVAL_SECONDS", 5
            ),
            maximum_photos=_positive_int("MAXIMUM_PHOTOS", 100),
            camera_capture_delay_ms=_positive_int("CAMERA_CAPTURE_DELAY_MS", 1000),
            video_dir=Path(os.getenv("VIDEO_DIR", PROJECT_ROOT / "data" / "videos")),
            maximum_videos=_positive_int("MAXIMUM_VIDEOS", 20),
            video_width=_positive_int("VIDEO_WIDTH", 1280),
            video_height=_positive_int("VIDEO_HEIGHT", 720),
            video_fps=_positive_int("VIDEO_FPS", 15),
            video_bitrate=_positive_int("VIDEO_BITRATE", 2_000_000),
            live_stream_width=_positive_int("LIVE_STREAM_WIDTH", 640),
            live_stream_height=_positive_int("LIVE_STREAM_HEIGHT", 360),
            live_stream_fps=_positive_int("LIVE_STREAM_FPS", 5),
            motion_threshold=_positive_float("MOTION_THRESHOLD", 12.0),
            motion_minimum_consecutive_frames=_positive_int(
                "MOTION_MINIMUM_CONSECUTIVE_FRAMES", 3
            ),
            motion_record_seconds=_positive_int("MOTION_RECORD_SECONDS", 20),
            motion_cooldown_seconds=_positive_int("MOTION_COOLDOWN_SECONDS", 30),
        )
