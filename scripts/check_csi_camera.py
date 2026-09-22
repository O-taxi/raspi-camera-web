#!/usr/bin/env python3
"""CSI接続のRaspberry Piカメラを診断する。

使い方:
    uv run python scripts/check_csi_camera.py [--capture] [--width PIXELS]
        [--height PIXELS] [--timeout-seconds SECONDS]

引数:
    --capture                  一時ディレクトリへJPEGを撮影して実撮影も確認する。
    --width PIXELS             テスト撮影の横幅（既定: 640）。
    --height PIXELS            テスト撮影の高さ（既定: 480）。
    --timeout-seconds SECONDS  各カメラコマンドのタイムアウト（既定: 15）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("0より大きい整数を指定してください")
    return number


def _find_command(current_name: str, legacy_name: str) -> str | None:
    return shutil.which(current_name) or shutil.which(legacy_name)


def _run(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout_seconds,
    )


def _has_no_camera_message(output: str) -> bool:
    normalized = output.lower()
    return "no cameras available" in normalized or "no camera available" in normalized


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CSI接続のRaspberry Piカメラモジュールの認識状態を確認します。"
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help="一時ディレクトリへJPEGを撮影して、実撮影も確認する",
    )
    parser.add_argument("--width", type=_positive_int, default=640, help="テスト撮影の横幅")
    parser.add_argument("--height", type=_positive_int, default=480, help="テスト撮影の高さ")
    parser.add_argument(
        "--timeout-seconds",
        type=_positive_int,
        default=15,
        help="各カメラコマンドのタイムアウト",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    hello_command = _find_command("rpicam-hello", "libcamera-hello")
    if hello_command is None:
        print(
            "NG: rpicam-helloまたはlibcamera-helloが見つかりません。"
            "rpicam-appsを導入してください。"
        )
        return 1

    try:
        result = _run([hello_command, "--list-cameras"], args.timeout_seconds)
    except subprocess.TimeoutExpired:
        print("NG: カメラ一覧の取得がタイムアウトしました。")
        return 1
    except OSError as exc:
        print(f"NG: カメラコマンドを実行できません: {exc}")
        return 1

    output = result.stdout.strip()
    if output:
        print(output)
    if result.returncode != 0 or _has_no_camera_message(output):
        print("NG: CSIカメラを認識できませんでした。")
        return 1

    print("OK: CSIカメラを認識しています。")
    if not args.capture:
        return 0

    still_command = _find_command("rpicam-still", "libcamera-still")
    if still_command is None:
        print("NG: rpicam-stillまたはlibcamera-stillが見つかりません。")
        return 1

    with tempfile.TemporaryDirectory(prefix="raspi-csi-camera-") as directory:
        output_path = Path(directory) / "test.jpg"
        command = [
            still_command,
            "--nopreview",
            "--width",
            str(args.width),
            "--height",
            str(args.height),
            "--timeout",
            "1000",
            "--output",
            str(output_path),
        ]
        try:
            result = _run(command, args.timeout_seconds)
        except subprocess.TimeoutExpired:
            print("NG: テスト撮影がタイムアウトしました。")
            return 1
        except OSError as exc:
            print(f"NG: テスト撮影コマンドを実行できません: {exc}")
            return 1

        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            print("NG: CSIカメラでJPEGを撮影できませんでした。")
            return 1
        if not output_path.read_bytes().startswith(b"\xff\xd8\xff"):
            print("NG: テスト撮影の出力がJPEGではありません。")
            return 1

    print("OK: CSIカメラでJPEGを撮影できました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
