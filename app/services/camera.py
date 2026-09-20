from __future__ import annotations

import asyncio
import base64
import math
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.services.photos import Photo, PhotoStore

CaptureFunction = Callable[[Path], Awaitable[None]]
Clock = Callable[[], float]

# A complete 1x1 pixel JPEG used by the development and CI camera backend.
MOCK_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////"
    "//////////////////////////////////////////2wBDAf//////////////////////////"
    "//////////////////////////////////////////////////////////wAARCAABAAEDASIA"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oA"
    "DAMBAAIQAxAAAAEf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAA"
    "AAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEB"
    "PwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAA"
    "AAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oA"
    "CAEDAQE/EB//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EB//xAAUEAEAAAAAAAAA"
    "AAAAAAAAAAAA/9oACAEBAAE/EB//2Q=="
)


class CameraBusyError(RuntimeError):
    """Raised when capture is already running or called too frequently."""

    def __init__(self, message: str, retry_after_seconds: int = 1) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class CameraCaptureError(RuntimeError):
    """Raised when the camera command cannot produce a photo."""


class CameraTimeoutError(CameraCaptureError):
    """Raised when capture exceeds its configured timeout."""


class CameraService:
    def __init__(
        self,
        settings: Settings,
        store: PhotoStore,
        capture_function: CaptureFunction | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self.settings = settings
        self.store = store
        if capture_function is not None:
            self._capture_function = capture_function
        elif settings.camera_backend == "mock":
            self._capture_function = self._capture_with_mock
        else:
            self._capture_function = self._capture_with_fswebcam
        self._clock = clock
        self._lock = asyncio.Lock()
        self._last_capture_finished_at: float | None = None

    async def capture(self) -> Photo:
        if self._lock.locked():
            raise CameraBusyError("A capture is already in progress")

        now = self._clock()
        if (
            self._last_capture_finished_at is not None
            and now - self._last_capture_finished_at
            < self.settings.minimum_capture_interval_seconds
        ):
            elapsed = now - self._last_capture_finished_at
            retry_after = math.ceil(
                self.settings.minimum_capture_interval_seconds - elapsed
            )
            raise CameraBusyError(
                "Please wait before taking another photo",
                retry_after_seconds=retry_after,
            )

        async with self._lock:
            photo_id = f"{datetime.now().astimezone():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
            output_path = self.store.path_for_new_photo(photo_id)

            try:
                try:
                    await asyncio.wait_for(
                        self._capture_function(output_path),
                        timeout=self.settings.capture_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    output_path.unlink(missing_ok=True)
                    raise CameraTimeoutError("Camera capture timed out") from exc
                except CameraCaptureError:
                    output_path.unlink(missing_ok=True)
                    raise
                except Exception as exc:
                    output_path.unlink(missing_ok=True)
                    raise CameraCaptureError("Camera capture failed") from exc

                if not output_path.is_file() or output_path.stat().st_size == 0:
                    output_path.unlink(missing_ok=True)
                    raise CameraCaptureError("Camera did not produce an image")

                self.store.remove_excess()
                return next(
                    photo for photo in self.store.list_photos() if photo.id == photo_id
                )
            finally:
                self._last_capture_finished_at = self._clock()

    async def _capture_with_fswebcam(self, output_path: Path) -> None:
        command = (
            self.settings.camera_command,
            "--device",
            self.settings.camera_device,
            "--resolution",
            f"{self.settings.camera_width}x{self.settings.camera_height}",
            "--no-banner",
            str(output_path),
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise CameraCaptureError("Camera command is not installed") from exc

        try:
            _, stderr = await process.communicate()
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise

        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise CameraCaptureError(message or "Camera command failed")

    async def _capture_with_mock(self, output_path: Path) -> None:
        output_path.write_bytes(MOCK_JPEG)
