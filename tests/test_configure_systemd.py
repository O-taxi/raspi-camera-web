from argparse import Namespace
from pathlib import Path

from scripts.configure_systemd import build_environment, render_unit


def test_render_unit_replaces_host_specific_values() -> None:
    template = (
        "User=<your-user>\nGroup=<your-group>\nWorkingDirectory=<project-dir>\n"
        "ReadWritePaths=<photo-dir>\nEnvironmentFile=-<env-file>\n"
        "Environment=PATH=<uv-bin-dir>:/usr/bin\nExecStart=/usr/bin/env uv run\n"
    )

    rendered = render_unit(
        template,
        user="camera-user",
        group="camera-group",
        project_dir=Path("/srv/raspi-camera-web"),
        photo_dir=Path("/var/lib/raspi-camera-web/photos"),
        env_path=Path("/etc/raspi-camera-web.env"),
        uv_path=Path("/home/camera-user/.local/bin/uv"),
    )

    assert "User=camera-user" in rendered
    assert "Group=camera-group" in rendered
    assert "WorkingDirectory=/srv/raspi-camera-web" in rendered
    assert "ReadWritePaths=/var/lib/raspi-camera-web/photos" in rendered
    assert "EnvironmentFile=-/etc/raspi-camera-web.env" in rendered
    assert "Environment=PATH=/home/camera-user/.local/bin:/usr/bin" in rendered
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
    )

    environment = build_environment(args, Path("/srv/photos"))

    assert 'PHOTO_DIR="/srv/photos"' in environment
    assert 'CAMERA_BACKEND="fswebcam"' in environment
    assert 'CAMERA_DEVICE="/dev/video2"' in environment
    assert 'MAXIMUM_PHOTOS="50"' in environment
