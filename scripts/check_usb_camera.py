#!/usr/bin/env python3
"""USB Video4Linux2カメラを診断する。

使い方:
    uv run --no-sync python scripts/check_usb_camera.py [--device PATH]...

引数:
    --device PATH  確認するV4L2デバイス。複数回指定可能。
                   省略時は /dev/video* をすべて確認する。
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import os
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

VIDIOC_QUERYCAP = 0x80685600
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_CAPTURE_MPLANE = 0x00001000
V4L2_CAP_READWRITE = 0x01000000
V4L2_CAP_STREAMING = 0x04000000
V4L2_CAP_DEVICE_CAPS = 0x80000000
CAPABILITY_STRUCT = struct.Struct("=16s32s32s6I")


@dataclass(frozen=True)
class CameraInfo:
    path: Path
    driver: str
    card: str
    bus_info: str
    version: int
    capabilities: int
    is_usb: bool
    usb_vendor_id: str | None
    usb_product_id: str | None
    usb_product: str | None

    @property
    def can_capture(self) -> bool:
        capture_flags = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_VIDEO_CAPTURE_MPLANE
        return bool(self.capabilities & capture_flags)


def _decode(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def _version(value: int) -> str:
    return f"{value >> 16}.{(value >> 8) & 0xff}.{value & 0xff}"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _usb_metadata(device: Path) -> tuple[str | None, str | None, str | None]:
    sysfs_device = Path("/sys/class/video4linux") / device.name / "device"
    try:
        current = sysfs_device.resolve(strict=True)
    except OSError:
        return None, None, None

    for parent in (current, *current.parents):
        vendor_id = _read_text(parent / "idVendor")
        product_id = _read_text(parent / "idProduct")
        if vendor_id is not None and product_id is not None:
            return vendor_id, product_id, _read_text(parent / "product")
        if parent == Path("/sys"):
            break
    return None, None, None


def query_camera(path: Path) -> CameraInfo:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        buffer = bytearray(CAPABILITY_STRUCT.size)
        fcntl.ioctl(descriptor, VIDIOC_QUERYCAP, buffer, True)
    finally:
        os.close(descriptor)

    driver, card, bus_info, version, capabilities, device_caps, *_ = (
        CAPABILITY_STRUCT.unpack(buffer)
    )
    effective_capabilities = (
        device_caps if capabilities & V4L2_CAP_DEVICE_CAPS else capabilities
    )
    decoded_bus_info = _decode(bus_info)
    vendor_id, product_id, product = _usb_metadata(path)
    return CameraInfo(
        path=path,
        driver=_decode(driver),
        card=_decode(card),
        bus_info=decoded_bus_info,
        version=version,
        capabilities=effective_capabilities,
        is_usb=decoded_bus_info.startswith("usb-") or vendor_id is not None,
        usb_vendor_id=vendor_id,
        usb_product_id=product_id,
        usb_product=product,
    )


def _capability_names(capabilities: int) -> list[str]:
    names = []
    if capabilities & V4L2_CAP_VIDEO_CAPTURE:
        names.append("video-capture")
    if capabilities & V4L2_CAP_VIDEO_CAPTURE_MPLANE:
        names.append("video-capture-mplane")
    if capabilities & V4L2_CAP_READWRITE:
        names.append("read/write")
    if capabilities & V4L2_CAP_STREAMING:
        names.append("streaming")
    return names


def _device_paths(requested_devices: list[str]) -> list[Path]:
    if requested_devices:
        return list(dict.fromkeys(Path(value) for value in requested_devices))
    return [Path(value) for value in sorted(glob.glob("/dev/video*"))]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="USBカメラのV4L2認識状態とアクセス権を確認します。"
    )
    parser.add_argument(
        "--device",
        action="append",
        default=[],
        metavar="PATH",
        help="確認するデバイス。複数回指定可能（省略時は/dev/video*）。",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    devices = _device_paths(args.device)
    if not devices:
        print("NG: /dev/video* が見つかりません。カメラがV4L2デバイスとして未認識です。")
        return 1

    usable_usb_cameras = 0
    for path in devices:
        print(f"\n[{path}]")
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            print("  NG: デバイスが存在しません。")
            continue
        except OSError as exc:
            print(f"  NG: デバイス情報を取得できません: {exc}")
            continue

        if not stat.S_ISCHR(mode):
            print("  NG: キャラクターデバイスではありません。")
            continue

        print(f"  読み取り権限: {'あり' if os.access(path, os.R_OK) else 'なし'}")
        print(f"  書き込み権限: {'あり' if os.access(path, os.W_OK) else 'なし'}")
        try:
            info = query_camera(path)
        except PermissionError:
            print("  NG: V4L2デバイスを開けません。videoグループへの所属を確認してください。")
            continue
        except OSError as exc:
            print(f"  NG: VIDIOC_QUERYCAPに失敗しました: {exc}")
            continue

        capabilities = _capability_names(info.capabilities)
        print(f"  カード名: {info.card or '(不明)'}")
        print(f"  ドライバー: {info.driver or '(不明)'} ({_version(info.version)})")
        print(f"  バス: {info.bus_info or '(不明)'}")
        print(f"  USBデバイス: {'はい' if info.is_usb else 'いいえ'}")
        if info.usb_vendor_id and info.usb_product_id:
            print(f"  USB ID: {info.usb_vendor_id}:{info.usb_product_id}")
        if info.usb_product:
            print(f"  USB製品名: {info.usb_product}")
        print(f"  機能: {', '.join(capabilities) if capabilities else '(該当なし)'}")
        print(f"  撮影対応: {'はい' if info.can_capture else 'いいえ'}")

        if info.is_usb and info.can_capture:
            usable_usb_cameras += 1

    if usable_usb_cameras:
        print(f"\nOK: 撮影可能なUSBカメラを{usable_usb_cameras}台認識しています。")
        return 0

    print("\nNG: 撮影可能なUSBカメラを確認できませんでした。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
