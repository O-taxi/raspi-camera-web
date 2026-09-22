from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.services.videos import VideoStore

LOGGER = logging.getLogger(__name__)
MJPEG_BOUNDARY = b"frame"
MOTION_SAMPLE_STRIDE = 4


@dataclass
class _Recording:
    video_id: str
    temporary_path: Path
    deadline: float


class Picamera2Service:
    """Own the CSI camera for live frames, still captures, and motion recordings."""

    def __init__(self, settings: Settings, video_store: VideoStore) -> None:
        self.settings = settings
        self.video_store = video_store
        self._camera: Any | None = None
        self._camera_lock = threading.Lock()
        self._frame_condition = asyncio.Condition()
        self._latest_jpeg: bytes | None = None
        self._frame_version = 0
        self._producer_task: asyncio.Task[None] | None = None
        self._previous_luma: bytes | None = None
        self._motion_frames = 0
        self._recording: _Recording | None = None
        self._recording_encoder: Any | None = None
        self._recording_output: Any | None = None
        self._last_recording_finished_at = 0.0
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await asyncio.to_thread(self._open_camera)
        self._started = True
        self._producer_task = asyncio.create_task(self._produce_frames())

    async def stop(self) -> None:
        producer_task = self._producer_task
        self._producer_task = None
        if producer_task is not None:
            producer_task.cancel()
            try:
                await producer_task
            except asyncio.CancelledError:
                pass

        if self._started:
            await asyncio.to_thread(self._close_camera)
            self._started = False

    async def capture_still(self, output_path: Path) -> None:
        if not self._started:
            raise RuntimeError("Picamera2 camera service is not running")
        await asyncio.to_thread(self._capture_still, output_path)

    async def mjpeg_frames(self) -> AsyncIterator[bytes]:
        version = -1
        while True:
            async with self._frame_condition:
                await self._frame_condition.wait_for(
                    lambda: self._frame_version != version or not self._started
                )
                if not self._started:
                    return
                jpeg = self._latest_jpeg
                version = self._frame_version

            if jpeg is not None:
                yield (
                    b"--"
                    + MJPEG_BOUNDARY
                    + b"\r\nContent-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
                    + jpeg
                    + b"\r\n"
                )

    def _open_camera(self) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise RuntimeError(
                "Picamera2 is not installed; install python3-picamera2 on Raspberry Pi OS"
            ) from exc

        camera = Picamera2()
        frame_duration_us = int(1_000_000 / self.settings.video_fps)
        configuration = camera.create_video_configuration(
            main={"size": (self.settings.video_width, self.settings.video_height)},
            lores={
                "size": (
                    self.settings.live_stream_width,
                    self.settings.live_stream_height,
                ),
                "format": "YUV420",
            },
            controls={"FrameDurationLimits": (frame_duration_us, frame_duration_us)},
        )
        camera.configure(configuration)
        camera.start()
        self._camera = camera

    def _close_camera(self) -> None:
        camera = self._camera
        if camera is None:
            return
        if self._recording is not None:
            self._finish_recording()
        with self._camera_lock:
            camera.stop()
            camera.close()
            self._camera = None

    def _capture_still(self, output_path: Path) -> None:
        camera = self._require_camera()
        with self._camera_lock:
            camera.capture_file(str(output_path), name="main")

    async def _produce_frames(self) -> None:
        interval = 1 / self.settings.live_stream_fps
        while True:
            started_at = time.monotonic()
            try:
                luma, jpeg = await asyncio.to_thread(self._capture_live_frame)
                motion_detected = self._detect_motion(luma)
                await self._update_recording(motion_detected)
                async with self._frame_condition:
                    self._latest_jpeg = jpeg
                    self._frame_version += 1
                    self._frame_condition.notify_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Picamera2 live frame capture failed")
                await asyncio.sleep(1)
                continue

            await asyncio.sleep(max(0, interval - (time.monotonic() - started_at)))

    def _capture_live_frame(self) -> tuple[bytes, bytes]:
        camera = self._require_camera()
        with self._camera_lock:
            frame = camera.capture_array("lores")
        luma = frame[
            : self.settings.live_stream_height, : self.settings.live_stream_width
        ].tobytes()
        return luma, self._encode_luma_jpeg(luma)

    def _encode_luma_jpeg(self, luma: bytes) -> bytes:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Pillow is required by the Picamera2 live stream") from exc

        image = Image.frombytes(
            "L",
            (self.settings.live_stream_width, self.settings.live_stream_height),
            luma,
        )
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=75, optimize=False)
        return buffer.getvalue()

    def _detect_motion(self, current_luma: bytes) -> bool:
        previous_luma = self._previous_luma
        self._previous_luma = current_luma
        if previous_luma is None:
            return False

        score = sum(
            abs(current_luma[index] - previous_luma[index])
            for index in range(0, len(current_luma), MOTION_SAMPLE_STRIDE)
        ) / ((len(current_luma) + MOTION_SAMPLE_STRIDE - 1) // MOTION_SAMPLE_STRIDE)
        if score >= self.settings.motion_threshold:
            self._motion_frames += 1
        else:
            self._motion_frames = 0
        return self._motion_frames >= self.settings.motion_minimum_consecutive_frames

    async def _update_recording(self, motion_detected: bool) -> None:
        now = time.monotonic()
        recording = self._recording
        if recording is not None:
            if motion_detected:
                recording.deadline = now + self.settings.motion_record_seconds
            elif now >= recording.deadline:
                await asyncio.to_thread(self._finish_recording)
            return

        if (
            motion_detected
            and now - self._last_recording_finished_at >= self.settings.motion_cooldown_seconds
        ):
            await asyncio.to_thread(self._start_recording, now)

    def _start_recording(self, now: float) -> None:
        try:
            from picamera2.encoders import H264Encoder
            from picamera2.outputs import FfmpegOutput
        except ImportError as exc:
            raise RuntimeError("Picamera2 recording support is not installed") from exc

        camera = self._require_camera()
        video_id = f"{datetime.now().astimezone():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
        temporary_path = self.video_store.path_for_recording(video_id)
        encoder = H264Encoder(bitrate=self.settings.video_bitrate)
        output = FfmpegOutput(str(temporary_path))
        with self._camera_lock:
            camera.start_recording(encoder, output, name="main")
            self._recording_encoder = encoder
            self._recording_output = output
            self._recording = _Recording(
                video_id=video_id,
                temporary_path=temporary_path,
                deadline=now + self.settings.motion_record_seconds,
            )

    def _finish_recording(self) -> None:
        recording = self._recording
        camera = self._camera
        if recording is None or camera is None:
            return
        try:
            with self._camera_lock:
                camera.stop_recording()
            final_path = self.video_store.path_for_new_video(recording.video_id)
            if recording.temporary_path.is_file() and recording.temporary_path.stat().st_size > 0:
                recording.temporary_path.replace(final_path)
                self.video_store.remove_excess()
            else:
                recording.temporary_path.unlink(missing_ok=True)
        finally:
            self._recording = None
            self._recording_encoder = None
            self._recording_output = None
            self._last_recording_finished_at = time.monotonic()

    def _require_camera(self) -> Any:
        if self._camera is None:
            raise RuntimeError("Picamera2 camera service is not running")
        return self._camera
