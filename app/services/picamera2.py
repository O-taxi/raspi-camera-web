from __future__ import annotations

import asyncio
import io
import json
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
    started_at: float
    deadline: float
    maximum_deadline: float


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
        self._motion_settling_until = 0.0
        self._motion_enabled = settings.motion_enabled
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._motion_enabled = await asyncio.to_thread(self._load_motion_enabled)
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

    @property
    def motion_enabled(self) -> bool:
        return self._motion_enabled

    async def set_motion_enabled(self, enabled: bool) -> bool:
        await asyncio.to_thread(self._save_motion_enabled, enabled)
        self._motion_enabled = enabled
        self._previous_luma = None
        self._motion_frames = 0
        self._motion_settling_until = 0.0
        recording = self._recording
        if not enabled and recording is not None:
            discard = (
                time.monotonic() - recording.started_at
                < self.settings.motion_min_record_seconds
            )
            await asyncio.to_thread(self._finish_recording, discard)
        return self._motion_enabled

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
                if self._motion_enabled:
                    motion_detected = self._detect_motion(luma)
                    await self._update_recording(motion_detected)
                else:
                    self._previous_luma = None
                    self._motion_frames = 0
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
        return self._encode_live_frame(frame)

    def _encode_live_frame(self, frame: Any) -> tuple[bytes, bytes]:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Pillow is required by the Picamera2 live stream") from exc

        width = self.settings.live_stream_width
        height = self.settings.live_stream_height
        if height % 4 != 0:
            raise RuntimeError("LIVE_STREAM_HEIGHT must be divisible by four for YUV420")

        luma_plane = frame[:height, :width]
        chroma_matrix_rows = height // 4
        u_plane = frame[height : height + chroma_matrix_rows, :width].reshape(
            height // 2, width // 2
        )
        v_plane = frame[
            height + chroma_matrix_rows : height + (2 * chroma_matrix_rows),
            :width,
        ].reshape(height // 2, width // 2)
        luma = luma_plane.tobytes()
        image = Image.merge(
            "YCbCr",
            (
                Image.fromarray(luma_plane),
                Image.fromarray(u_plane).resize((width, height), Image.BILINEAR),
                Image.fromarray(v_plane).resize((width, height), Image.BILINEAR),
            ),
        ).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=75, optimize=False)
        return luma, buffer.getvalue()

    def _detect_motion(self, current_luma: bytes) -> bool:
        previous_luma = self._previous_luma
        self._previous_luma = current_luma
        if previous_luma is None:
            return False

        changed_pixels = 0
        brightened_pixels = 0
        darkened_pixels = 0
        sample_count = 0
        tile_sample_counts: dict[tuple[int, int], int] = {}
        tile_changed_counts: dict[tuple[int, int], int] = {}
        width = self.settings.live_stream_width
        tile_size = self.settings.motion_analysis_tile_size
        for index in range(0, len(current_luma), MOTION_SAMPLE_STRIDE):
            difference = current_luma[index] - previous_luma[index]
            sample_count += 1
            tile = ((index % width) // tile_size, (index // width) // tile_size)
            tile_sample_counts[tile] = tile_sample_counts.get(tile, 0) + 1
            if abs(difference) < self.settings.motion_threshold:
                continue
            changed_pixels += 1
            tile_changed_counts[tile] = tile_changed_counts.get(tile, 0) + 1
            if difference > 0:
                brightened_pixels += 1
            else:
                darkened_pixels += 1

        if changed_pixels == 0:
            self._motion_frames = 0
            return False

        changed_ratio = changed_pixels / sample_count
        directional_ratio = max(brightened_pixels, darkened_pixels) / changed_pixels
        now = time.monotonic()
        if (
            changed_ratio >= self.settings.motion_illumination_changed_ratio
            and directional_ratio >= self.settings.motion_illumination_direction_ratio
        ):
            self._motion_frames = 0
            self._motion_settling_until = now + self.settings.motion_settle_seconds
            return False

        if now < self._motion_settling_until:
            self._motion_frames = 0
            return False

        largest_tile_changed_ratio = max(
            changed_count / tile_sample_counts[tile]
            for tile, changed_count in tile_changed_counts.items()
        )
        if largest_tile_changed_ratio >= self.settings.motion_min_changed_ratio:
            self._motion_frames += 1
        else:
            self._motion_frames = 0
        return self._motion_frames >= self.settings.motion_minimum_consecutive_frames

    async def _update_recording(self, motion_detected: bool) -> None:
        now = time.monotonic()
        recording = self._recording
        if recording is not None:
            if now >= recording.maximum_deadline:
                await asyncio.to_thread(self._finish_recording)
            elif motion_detected:
                recording.deadline = min(
                    now + self.settings.motion_record_seconds,
                    recording.maximum_deadline,
                )
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
            camera.start_encoder(encoder, output, name="main")
            self._recording_encoder = encoder
            self._recording_output = output
            self._recording = _Recording(
                video_id=video_id,
                temporary_path=temporary_path,
                started_at=now,
                deadline=now + self.settings.motion_record_seconds,
                maximum_deadline=now + self.settings.motion_max_record_seconds,
            )

    def _finish_recording(self, discard: bool = False) -> None:
        recording = self._recording
        camera = self._camera
        if recording is None or camera is None:
            return
        try:
            with self._camera_lock:
                if self._recording_encoder is not None:
                    camera.stop_encoder(self._recording_encoder)
            final_path = self.video_store.path_for_new_video(recording.video_id)
            duration_seconds = time.monotonic() - recording.started_at
            if (
                not discard
                and duration_seconds >= self.settings.motion_min_record_seconds
                and recording.temporary_path.is_file()
                and recording.temporary_path.stat().st_size > 0
            ):
                recording.temporary_path.replace(final_path)
                self.video_store.set_duration(recording.video_id, duration_seconds)
                self.video_store.remove_excess()
            else:
                recording.temporary_path.unlink(missing_ok=True)
        finally:
            self._recording = None
            self._recording_encoder = None
            self._recording_output = None
            self._last_recording_finished_at = time.monotonic()

    def _load_motion_enabled(self) -> bool:
        try:
            state = json.loads(self.settings.motion_state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self.settings.motion_enabled
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Unable to read motion detection state: %s", exc)
            return self.settings.motion_enabled

        enabled = state.get("enabled") if isinstance(state, dict) else None
        if isinstance(enabled, bool):
            return enabled
        LOGGER.warning("Motion detection state is invalid; using configured default")
        return self.settings.motion_enabled

    def _save_motion_enabled(self, enabled: bool) -> None:
        path = self.settings.motion_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_text(
                json.dumps({"enabled": enabled}) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _require_camera(self) -> Any:
        if self._camera is None:
            raise RuntimeError("Picamera2 camera service is not running")
        return self._camera
