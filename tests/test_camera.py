import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.camera import (
    CameraBusyError,
    CameraCaptureError,
    CameraService,
    CameraTimeoutError,
)
from app.services.photos import PhotoStore


@pytest.mark.asyncio
async def test_capture_creates_photo(settings) -> None:
    async def capture(path: Path) -> None:
        path.write_bytes(b"jpeg")

    service = CameraService(settings, PhotoStore(settings.photo_dir, 3), capture)

    photo = await service.capture()

    assert photo.url == f"/photos/{photo.id}"
    assert settings.photo_dir.joinpath(f"{photo.id}.jpg").read_bytes() == b"jpeg"


@pytest.mark.asyncio
async def test_capture_reports_command_failure(settings) -> None:
    async def capture(_path: Path) -> None:
        raise CameraCaptureError("device unavailable")

    service = CameraService(settings, PhotoStore(settings.photo_dir, 3), capture)

    with pytest.raises(CameraCaptureError):
        await service.capture()


@pytest.mark.asyncio
async def test_capture_times_out(settings) -> None:
    async def capture(_path: Path) -> None:
        await asyncio.sleep(2)

    service = CameraService(settings, PhotoStore(settings.photo_dir, 3), capture)

    with pytest.raises(CameraTimeoutError):
        await service.capture()


@pytest.mark.asyncio
async def test_capture_rejects_concurrent_request(settings) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()

    async def capture(path: Path) -> None:
        started.set()
        await finish.wait()
        path.write_bytes(b"jpeg")

    service = CameraService(settings, PhotoStore(settings.photo_dir, 3), capture)
    first_capture = asyncio.create_task(service.capture())
    await started.wait()

    with pytest.raises(CameraBusyError):
        await service.capture()

    finish.set()
    await first_capture


@pytest.mark.asyncio
async def test_capture_interval_starts_after_previous_capture_finishes(
    settings,
) -> None:
    times = iter((100.0, 105.0, 105.5))

    async def capture(path: Path) -> None:
        path.write_bytes(b"jpeg")

    service = CameraService(
        settings,
        PhotoStore(settings.photo_dir, 3),
        capture,
        clock=lambda: next(times),
    )
    await service.capture()

    with pytest.raises(CameraBusyError) as error:
        await service.capture()

    assert error.value.retry_after_seconds == 1


@pytest.mark.asyncio
async def test_mock_capture_creates_valid_jpeg_without_external_command(settings) -> None:
    mock_settings = replace(settings, camera_backend="mock")
    service = CameraService(
        mock_settings,
        PhotoStore(mock_settings.photo_dir, mock_settings.maximum_photos),
    )

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as subprocess:
        photo = await service.capture()

    image = mock_settings.photo_dir.joinpath(f"{photo.id}.jpg").read_bytes()
    assert image.startswith(b"\xff\xd8\xff")
    assert image.endswith(b"\xff\xd9")
    assert b"JFIF\x00" in image
    subprocess.assert_not_awaited()


@pytest.mark.asyncio
async def test_rpicam_capture_uses_csi_camera_command(settings) -> None:
    rpicam_settings = replace(
        settings,
        camera_backend="rpicam",
        camera_command="rpicam-still",
        camera_capture_delay_ms=1200,
    )
    process = AsyncMock()
    process.returncode = 0
    finish = asyncio.Event()

    async def communicate() -> tuple[bytes, bytes]:
        await finish.wait()
        return b"", b""

    process.communicate.side_effect = communicate

    with patch("asyncio.create_subprocess_exec", return_value=process) as subprocess:
        service = CameraService(
            rpicam_settings,
            PhotoStore(rpicam_settings.photo_dir, rpicam_settings.maximum_photos),
        )
        capture = asyncio.create_task(service.capture())
        await asyncio.sleep(0)
        command = subprocess.await_args.args
        output_path = Path(command[-1])
        output_path.write_bytes(b"jpeg")
        finish.set()
        await capture

    assert command == (
        "rpicam-still",
        "--nopreview",
        "--width",
        "640",
        "--height",
        "480",
        "--timeout",
        "1200",
        "--output",
        str(output_path),
    )
