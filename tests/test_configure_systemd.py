from argparse import Namespace
from pathlib import Path

from scripts.configure_systemd import build_environment, render_unit


def test_render_unit_replaces_host_specific_values() -> None:
    template = (
        "User=<your-user>\nGroup=<your-group>\nWorkingDirectory=<project-dir>\n"
        "ReadWritePaths=<photo-dir> <video-dir>\nEnvironmentFile=-<env-file>\n"
        "Environment=PATH=<uv-bin-dir>:/usr/bin\n"
        "Environment=UV_CACHE_DIR=/run/raspi-camera-web/uv-cache\n"
        "RuntimeDirectory=raspi-camera-web\nExecStart=/usr/bin/env uv run\n"
    )

    rendered = render_unit(
        template,
        user="camera-user",
        group="camera-group",
        project_dir=Path("/srv/raspi-camera-web"),
        photo_dir=Path("/var/lib/raspi-camera-web/photos"),
        video_dir=Path("/var/lib/raspi-camera-web/videos"),
        env_path=Path("/etc/raspi-camera-web.env"),
        uv_path=Path("/home/camera-user/.local/bin/uv"),
    )

    assert "User=camera-user" in rendered
    assert "Group=camera-group" in rendered
    assert "WorkingDirectory=/srv/raspi-camera-web" in rendered
    assert (
        "ReadWritePaths=/var/lib/raspi-camera-web/photos "
        "/var/lib/raspi-camera-web/videos" in rendered
    )
    assert "EnvironmentFile=-/etc/raspi-camera-web.env" in rendered
    assert "Environment=PATH=/home/camera-user/.local/bin:/usr/bin" in rendered
    assert "Environment=UV_CACHE_DIR=/run/raspi-camera-web/uv-cache" in rendered
    assert "RuntimeDirectory=raspi-camera-web" in rendered
    assert "ExecStart=/usr/bin/env uv run" in rendered
    assert "<" not in rendered


def test_build_environment_contains_camera_settings() -> None:
    args = Namespace(
        camera_backend="fswebcam",
        camera_command="fswebcam",
        camera_device="/dev/video2",
        camera_width=640,
        camera_height=480,
        capture_timeout_seconds=10,
        minimum_capture_interval_seconds=2,
        maximum_photos=50,
        camera_capture_delay_ms=1000,
        maximum_videos=20,
        video_width=1280,
        video_height=720,
        video_fps=15,
        video_bitrate=2_000_000,
        live_stream_width=640,
        live_stream_height=360,
        live_stream_fps=5,
        motion_threshold=12.0,
        motion_analysis_tile_size=32,
        motion_min_changed_ratio=0.10,
        motion_illumination_changed_ratio=0.65,
        motion_illumination_direction_ratio=0.90,
        motion_settle_seconds=5,
        motion_minimum_consecutive_frames=3,
        motion_record_seconds=20,
        motion_min_record_seconds=2,
        motion_max_record_seconds=60,
        motion_cooldown_seconds=30,
        motion_enabled=True,
    )

    environment = build_environment(args, Path("/srv/photos"), Path("/srv/videos"))

    assert 'PHOTO_DIR="/srv/photos"' in environment
    assert 'CAMERA_BACKEND="fswebcam"' in environment
    assert 'CAMERA_DEVICE="/dev/video2"' in environment
    assert 'MAXIMUM_PHOTOS="50"' in environment
    assert 'CAMERA_CAPTURE_DELAY_MS="1000"' in environment
    assert 'VIDEO_DIR="/srv/videos"' in environment
    assert 'MOTION_MAX_RECORD_SECONDS="60"' in environment
    assert 'MOTION_ANALYSIS_TILE_SIZE="32"' in environment
    assert 'MOTION_ENABLED="True"' in environment


def test_build_environment_defaults_to_rpicam_still_for_csi_camera() -> None:
    args = Namespace(
        camera_backend="rpicam",
        camera_command=None,
        camera_device="/dev/video0",
        camera_width=1280,
        camera_height=720,
        capture_timeout_seconds=15,
        minimum_capture_interval_seconds=5,
        maximum_photos=100,
        camera_capture_delay_ms=1000,
        maximum_videos=20,
        video_width=1280,
        video_height=720,
        video_fps=15,
        video_bitrate=2_000_000,
        live_stream_width=640,
        live_stream_height=360,
        live_stream_fps=5,
        motion_threshold=12.0,
        motion_analysis_tile_size=32,
        motion_min_changed_ratio=0.10,
        motion_illumination_changed_ratio=0.65,
        motion_illumination_direction_ratio=0.90,
        motion_settle_seconds=5,
        motion_minimum_consecutive_frames=3,
        motion_record_seconds=20,
        motion_min_record_seconds=2,
        motion_max_record_seconds=60,
        motion_cooldown_seconds=30,
        motion_enabled=True,
    )

    environment = build_environment(args, Path("/srv/photos"), Path("/srv/videos"))

    assert 'CAMERA_COMMAND="rpicam-still"' in environment


def test_build_environment_adds_system_packages_for_picamera2() -> None:
    args = Namespace(
        camera_backend="picamera2",
        camera_command=None,
        camera_device="/dev/video0",
        camera_width=1280,
        camera_height=720,
        capture_timeout_seconds=15,
        minimum_capture_interval_seconds=5,
        maximum_photos=100,
        camera_capture_delay_ms=1000,
        maximum_videos=20,
        video_width=1280,
        video_height=720,
        video_fps=15,
        video_bitrate=2_000_000,
        live_stream_width=640,
        live_stream_height=360,
        live_stream_fps=5,
        motion_threshold=12.0,
        motion_analysis_tile_size=32,
        motion_min_changed_ratio=0.10,
        motion_illumination_changed_ratio=0.65,
        motion_illumination_direction_ratio=0.90,
        motion_settle_seconds=5,
        motion_minimum_consecutive_frames=3,
        motion_record_seconds=20,
        motion_min_record_seconds=2,
        motion_max_record_seconds=60,
        motion_cooldown_seconds=30,
        motion_enabled=True,
    )

    environment = build_environment(args, Path("/srv/photos"), Path("/srv/videos"))

    assert 'CAMERA_COMMAND="picamera2"' in environment
    assert 'PYTHONPATH="/usr/lib/python3/dist-packages"' in environment
