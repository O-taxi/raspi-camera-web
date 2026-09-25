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


def _boolean(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    if raw_value.lower() in ("1", "true", "yes", "on"):
        return True
    if raw_value.lower() in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be true or false")


def _ratio(name: str, default: float) -> float:
    value = _positive_float(name, default)
    if value > 1:
        raise ValueError(f"{name} must be at most one")
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
    motion_analysis_tile_size: int = 32
    motion_min_changed_ratio: float = 0.10
    motion_illumination_changed_ratio: float = 0.65
    motion_illumination_direction_ratio: float = 0.90
    motion_settle_seconds: int = 5
    motion_minimum_consecutive_frames: int = 3
    motion_record_seconds: int = 20
    motion_min_record_seconds: int = 2
    motion_max_record_seconds: int = 60
    motion_cooldown_seconds: int = 30
    motion_enabled: bool = True
    motion_state_path: Path = PROJECT_ROOT / "data" / "videos" / ".motion-state.json"
    rotation_state_path: Path = PROJECT_ROOT / "data" / "videos" / ".rotation-state.json"
    maximum_video_bytes: int = 500_000_000
    minimum_free_disk_bytes: int = 100_000_000

    @classmethod
    def from_environment(cls) -> Settings:
        camera_backend = _camera_backend()
        video_dir = Path(os.getenv("VIDEO_DIR", PROJECT_ROOT / "data" / "videos"))
        motion_record_seconds = _positive_int("MOTION_RECORD_SECONDS", 20)
        motion_min_record_seconds = _positive_int("MOTION_MIN_RECORD_SECONDS", 2)
        motion_max_record_seconds = _positive_int("MOTION_MAX_RECORD_SECONDS", 60)
        if motion_max_record_seconds < motion_record_seconds:
            raise ValueError("MOTION_MAX_RECORD_SECONDS must be at least MOTION_RECORD_SECONDS")
        if motion_min_record_seconds > motion_record_seconds:
            raise ValueError("MOTION_MIN_RECORD_SECONDS must not exceed MOTION_RECORD_SECONDS")
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
            video_dir=video_dir,
            maximum_videos=_positive_int("MAXIMUM_VIDEOS", 20),
            maximum_video_bytes=_positive_int("MAXIMUM_VIDEO_BYTES", 500_000_000),
            minimum_free_disk_bytes=_positive_int("MINIMUM_FREE_DISK_BYTES", 100_000_000),
            video_width=_positive_int("VIDEO_WIDTH", 1280),
            video_height=_positive_int("VIDEO_HEIGHT", 720),
            video_fps=_positive_int("VIDEO_FPS", 15),
            video_bitrate=_positive_int("VIDEO_BITRATE", 2_000_000),
            live_stream_width=_positive_int("LIVE_STREAM_WIDTH", 640),
            live_stream_height=_positive_int("LIVE_STREAM_HEIGHT", 360),
            live_stream_fps=_positive_int("LIVE_STREAM_FPS", 5),
            motion_threshold=_positive_float("MOTION_THRESHOLD", 12.0),
            motion_analysis_tile_size=_positive_int("MOTION_ANALYSIS_TILE_SIZE", 32),
            motion_min_changed_ratio=_ratio("MOTION_MIN_CHANGED_RATIO", 0.10),
            motion_illumination_changed_ratio=_ratio(
                "MOTION_ILLUMINATION_CHANGED_RATIO", 0.65
            ),
            motion_illumination_direction_ratio=_ratio(
                "MOTION_ILLUMINATION_DIRECTION_RATIO", 0.90
            ),
            motion_settle_seconds=_positive_int("MOTION_SETTLE_SECONDS", 5),
            motion_minimum_consecutive_frames=_positive_int(
                "MOTION_MINIMUM_CONSECUTIVE_FRAMES", 3
            ),
            motion_record_seconds=motion_record_seconds,
            motion_min_record_seconds=motion_min_record_seconds,
            motion_max_record_seconds=motion_max_record_seconds,
            motion_cooldown_seconds=_positive_int("MOTION_COOLDOWN_SECONDS", 30),
            motion_enabled=_boolean("MOTION_ENABLED", True),
            motion_state_path=Path(
                os.getenv("MOTION_STATE_PATH", video_dir / ".motion-state.json")
            ),
            rotation_state_path=Path(
                os.getenv("ROTATION_STATE_PATH", video_dir / ".rotation-state.json")
            ),
        )
