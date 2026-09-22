#!/usr/bin/env python3
"""実機固有のsystemd unitとアプリ設定を生成する。

使い方:
    uv run python scripts/configure_systemd.py [OPTIONS]

主要引数:
    --dry-run                    生成内容だけを表示して書き込まない。
    --enable-now                 生成後にsystemdを有効化して起動する。
    --camera-backend BACKEND     fswebcam、rpicam、picamera2、mockから選択する。
    --camera-device PATH         USBカメラのV4L2デバイスを指定する。
    --photo-dir PATH             写真保存先を指定する。
    --video-dir PATH             動画保存先を指定する。
    --motion-max-record-seconds N  1本の動体検知録画の上限秒数を指定する。
    --motion-settle-seconds N    照明変化後の検知待機秒数を指定する。
    --[no-]motion-enabled        動体検知の既定の有効状態を指定する。
    --force                      既存のunitと環境ファイルを上書きする。

全引数は `uv run python scripts/configure_systemd.py --help` で確認する。
"""

from __future__ import annotations

import argparse
import getpass
import grp
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UNIT_TEMPLATE = PROJECT_ROOT / "systemd" / "raspi-camera-web.service"
DEFAULT_UNIT_PATH = Path("/etc/systemd/system/raspi-camera-web.service")
DEFAULT_ENV_PATH = Path("/etc/raspi-camera-web.env")


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("0より大きい整数を指定してください")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("0より大きい数値を指定してください")
    return number


def _ratio(value: str) -> float:
    number = _positive_float(value)
    if number > 1:
        raise argparse.ArgumentTypeError("1以下の数値を指定してください")
    return number


def _default_user() -> str:
    return os.environ.get("SUDO_USER") or getpass.getuser()


def _environment_value(value: str | Path | int | float) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _default_camera_command(camera_backend: str) -> str:
    if camera_backend == "rpicam":
        return "rpicam-still"
    if camera_backend == "picamera2":
        return "picamera2"
    return "fswebcam"


def build_environment(args: argparse.Namespace, photo_dir: Path, video_dir: Path) -> str:
    values: tuple[tuple[str, str | Path | int | float], ...] = (
        ("PHOTO_DIR", photo_dir),
        ("VIDEO_DIR", video_dir),
        ("CAMERA_BACKEND", args.camera_backend),
        ("CAMERA_COMMAND", args.camera_command or _default_camera_command(args.camera_backend)),
        ("CAMERA_DEVICE", args.camera_device),
        ("CAMERA_WIDTH", args.camera_width),
        ("CAMERA_HEIGHT", args.camera_height),
        ("CAPTURE_TIMEOUT_SECONDS", args.capture_timeout_seconds),
        ("MINIMUM_CAPTURE_INTERVAL_SECONDS", args.minimum_capture_interval_seconds),
        ("MAXIMUM_PHOTOS", args.maximum_photos),
        ("CAMERA_CAPTURE_DELAY_MS", args.camera_capture_delay_ms),
        ("MAXIMUM_VIDEOS", args.maximum_videos),
        ("VIDEO_WIDTH", args.video_width),
        ("VIDEO_HEIGHT", args.video_height),
        ("VIDEO_FPS", args.video_fps),
        ("VIDEO_BITRATE", args.video_bitrate),
        ("LIVE_STREAM_WIDTH", args.live_stream_width),
        ("LIVE_STREAM_HEIGHT", args.live_stream_height),
        ("LIVE_STREAM_FPS", args.live_stream_fps),
        ("MOTION_THRESHOLD", args.motion_threshold),
        ("MOTION_MIN_CHANGED_RATIO", args.motion_min_changed_ratio),
        ("MOTION_ILLUMINATION_CHANGED_RATIO", args.motion_illumination_changed_ratio),
        ("MOTION_ILLUMINATION_DIRECTION_RATIO", args.motion_illumination_direction_ratio),
        ("MOTION_SETTLE_SECONDS", args.motion_settle_seconds),
        ("MOTION_MINIMUM_CONSECUTIVE_FRAMES", args.motion_minimum_consecutive_frames),
        ("MOTION_RECORD_SECONDS", args.motion_record_seconds),
        ("MOTION_MAX_RECORD_SECONDS", args.motion_max_record_seconds),
        ("MOTION_COOLDOWN_SECONDS", args.motion_cooldown_seconds),
        ("MOTION_ENABLED", args.motion_enabled),
    )
    if args.camera_backend == "picamera2":
        values += (("PYTHONPATH", "/usr/lib/python3/dist-packages"),)
    return "".join(f"{name}={_environment_value(value)}\n" for name, value in values)


def render_unit(
    template: str,
    user: str,
    group: str,
    project_dir: Path,
    photo_dir: Path,
    video_dir: Path,
    env_path: Path,
    uv_path: Path,
) -> str:
    replacements = {
        "<your-user>": user,
        "<your-group>": group,
        "<project-dir>": str(project_dir),
        "<photo-dir>": str(photo_dir),
        "<video-dir>": str(video_dir),
        "<env-file>": str(env_path),
        "<uv-bin-dir>": str(uv_path.parent),
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    if "<" in rendered or ">" in rendered:
        raise ValueError("systemd unitに未解決のプレースホルダーがあります")
    return rendered


def _privileged_command(*command: str) -> tuple[str, ...]:
    if os.geteuid() == 0:
        return command
    return ("sudo", *command)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="実機固有のsystemd unitと/etc/raspi-camera-web.envを生成します。"
    )
    parser.add_argument("--user", default=_default_user(), help="サービスを実行するユーザー")
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=PROJECT_ROOT,
        help="raspi-camera-webの絶対パス",
    )
    parser.add_argument(
        "--photo-dir",
        type=Path,
        help="写真保存先（既定: <project-dir>/data/photos）",
    )
    parser.add_argument(
        "--camera-backend",
        choices=("fswebcam", "rpicam", "picamera2", "mock"),
        default="fswebcam",
    )
    parser.add_argument(
        "--camera-command",
        help="撮影コマンド（既定: fswebcam、rpicamではrpicam-still）",
    )
    parser.add_argument("--camera-device", default="/dev/video0")
    parser.add_argument("--camera-width", type=_positive_int, default=1280)
    parser.add_argument("--camera-height", type=_positive_int, default=720)
    parser.add_argument("--capture-timeout-seconds", type=_positive_int, default=15)
    parser.add_argument(
        "--minimum-capture-interval-seconds", type=_positive_int, default=5
    )
    parser.add_argument("--maximum-photos", type=_positive_int, default=100)
    parser.add_argument("--camera-capture-delay-ms", type=_positive_int, default=1000)
    parser.add_argument(
        "--video-dir",
        type=Path,
        help="動画保存先（既定: <project-dir>/data/videos）",
    )
    parser.add_argument("--maximum-videos", type=_positive_int, default=20)
    parser.add_argument("--video-width", type=_positive_int, default=1280)
    parser.add_argument("--video-height", type=_positive_int, default=720)
    parser.add_argument("--video-fps", type=_positive_int, default=15)
    parser.add_argument("--video-bitrate", type=_positive_int, default=2_000_000)
    parser.add_argument("--live-stream-width", type=_positive_int, default=640)
    parser.add_argument("--live-stream-height", type=_positive_int, default=360)
    parser.add_argument("--live-stream-fps", type=_positive_int, default=5)
    parser.add_argument("--motion-threshold", type=_positive_float, default=12.0)
    parser.add_argument("--motion-min-changed-ratio", type=_ratio, default=0.003)
    parser.add_argument("--motion-illumination-changed-ratio", type=_ratio, default=0.65)
    parser.add_argument("--motion-illumination-direction-ratio", type=_ratio, default=0.90)
    parser.add_argument("--motion-settle-seconds", type=_positive_int, default=5)
    parser.add_argument("--motion-minimum-consecutive-frames", type=_positive_int, default=3)
    parser.add_argument("--motion-record-seconds", type=_positive_int, default=20)
    parser.add_argument("--motion-max-record-seconds", type=_positive_int, default=60)
    parser.add_argument("--motion-cooldown-seconds", type=_positive_int, default=30)
    parser.add_argument(
        "--motion-enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="動体検知の既定状態（既定: 有効）",
    )
    parser.add_argument("--unit-path", type=Path, default=DEFAULT_UNIT_PATH)
    parser.add_argument("--env-path", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument(
        "--uv-path",
        type=Path,
        default=Path(shutil.which("uv") or "uv"),
        help="uv実行ファイルの絶対パス（既定: PATHから検出）",
    )
    parser.add_argument("--force", action="store_true", help="既存の設定ファイルを上書きする")
    parser.add_argument(
        "--enable-now",
        action="store_true",
        help="生成後にsystemdを再読み込みし、サービスを有効化・起動する",
    )
    parser.add_argument("--dry-run", action="store_true", help="内容を表示するだけで変更しない")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.motion_max_record_seconds < args.motion_record_seconds:
        print(
            "エラー: --motion-max-record-secondsは--motion-record-seconds以上にしてください。",
            file=sys.stderr,
        )
        return 2
    try:
        account = pwd.getpwnam(args.user)
    except KeyError:
        print(f"エラー: ユーザー {args.user!r} は存在しません。", file=sys.stderr)
        return 2
    if account.pw_uid == 0:
        print("エラー: サービス実行ユーザーにrootは指定できません。", file=sys.stderr)
        return 2
    group_name = grp.getgrgid(account.pw_gid).gr_name

    project_dir = args.project_dir.expanduser().resolve()
    photo_dir = (args.photo_dir or project_dir / "data" / "photos").expanduser().resolve()
    video_dir = (args.video_dir or project_dir / "data" / "videos").expanduser().resolve()
    uv_path = args.uv_path.expanduser().resolve()
    if any(
        character.isspace() for character in f"{project_dir}{photo_dir}{video_dir}{uv_path}"
    ):
        print(
            "エラー: project-dir、photo-dir、video-dir、uv-pathに空白は使用できません。",
            file=sys.stderr,
        )
        return 2
    if not (project_dir / "app" / "main.py").is_file():
        print(f"エラー: {project_dir} にアプリが見つかりません。", file=sys.stderr)
        return 2
    if not uv_path.is_file():
        print(f"エラー: uv実行ファイル {uv_path} が見つかりません。", file=sys.stderr)
        return 2

    template = UNIT_TEMPLATE.read_text(encoding="utf-8")
    unit = render_unit(
        template,
        args.user,
        group_name,
        project_dir,
        photo_dir,
        video_dir,
        args.env_path,
        uv_path,
    )
    environment = build_environment(args, photo_dir, video_dir)

    if args.dry_run:
        print(f"--- {args.unit_path} ---\n{unit}", end="")
        print(f"--- {args.env_path} ---\n{environment}", end="")
        return 0
    try:
        if not args.force:
            existing_paths = [path for path in (args.unit_path, args.env_path) if path.exists()]
            if existing_paths:
                paths = ", ".join(str(path) for path in existing_paths)
                raise FileExistsError(
                    f"{paths} は既に存在します。上書きするには --force が必要です"
                )
        with tempfile.TemporaryDirectory(prefix="raspi-camera-web-config-") as directory:
            temporary_directory = Path(directory)
            temporary_env = temporary_directory / args.env_path.name
            temporary_unit = temporary_directory / args.unit_path.name
            temporary_env.write_text(environment, encoding="utf-8")
            temporary_unit.write_text(unit, encoding="utf-8")

            subprocess.run(
                _privileged_command(
                    "install",
                    "-d",
                    "-o",
                    args.user,
                    "-g",
                    group_name,
                    "-m",
                    "0750",
                    str(photo_dir),
                ),
                check=True,
            )
            subprocess.run(
                _privileged_command(
                    "install",
                    "-d",
                    "-o",
                    args.user,
                    "-g",
                    group_name,
                    "-m",
                    "0750",
                    str(video_dir),
                ),
                check=True,
            )
            subprocess.run(
                _privileged_command(
                    "install",
                    "-o",
                    "root",
                    "-g",
                    "root",
                    "-m",
                    "0600",
                    str(temporary_env),
                    str(args.env_path),
                ),
                check=True,
            )
            subprocess.run(
                _privileged_command(
                    "install",
                    "-o",
                    "root",
                    "-g",
                    "root",
                    "-m",
                    "0644",
                    str(temporary_unit),
                    str(args.unit_path),
                ),
                check=True,
            )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    print(f"systemd unit: {args.unit_path}")
    print(f"環境設定: {args.env_path}")
    print(f"写真保存先: {photo_dir}")
    print(f"動画保存先: {video_dir}")

    if args.enable_now:
        try:
            subprocess.run(
                _privileged_command("systemctl", "daemon-reload"),
                check=True,
            )
            subprocess.run(
                _privileged_command(
                    "systemctl", "enable", "--now", args.unit_path.name
                ),
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"エラー: systemctlの実行に失敗しました: {exc}", file=sys.stderr)
            return 1
        print("raspi-camera-web.serviceを有効化して起動しました。")
    else:
        print("次に sudo systemctl daemon-reload を実行してください。")
        print("起動する場合は sudo systemctl enable --now raspi-camera-web.service を実行します。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
