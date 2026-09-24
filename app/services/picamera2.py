from __future__ import annotations

import asyncio
import io
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.services.motion import ShiftedLuma, estimate_frame_shift, smooth_luma
from app.services.videos import VideoStorageFullError, VideoStore

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
        self._control_lock = asyncio.Lock()
        self._frame_condition = asyncio.Condition()
        self._latest_jpeg: bytes | None = None
        self._frame_version = 0
        self._producer_task: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._previous_luma: bytes | None = None
        self._motion_frames = 0
        self._tile_motion_frames: dict[tuple[int, int], int] = {}
        self._motion_analysis: dict[str, Any] | None = None
        self._last_recording_trigger: dict[str, Any] | None = None
        self._recording: _Recording | None = None
        self._recording_encoder: Any | None = None
        self._recording_output: Any | None = None
        self._last_recording_finished_at = 0.0
        self._motion_settling_until = 0.0
        self._motion_enabled = settings.motion_enabled
        self._started = False
        self._stopping = False
        self._last_frame_at: str | None = None
        self._last_frame_monotonic: float | None = None
        self._started_at: float | None = None
        self._frame_error = False
        self._recording_error: str | None = None

    async def start(self) -> None:
        if self._started:
            return
        self._motion_enabled = await asyncio.to_thread(self._load_motion_enabled)
        await asyncio.to_thread(self.video_store.recover)
        await asyncio.to_thread(self._open_camera)
        self._stopping = False
        self._started = True
        self._started_at = time.monotonic()
        self._producer_task = asyncio.create_task(self._produce_frames())
        self._monitor_task = asyncio.create_task(self._monitor_recording())

    async def stop(self) -> None:
        self._stopping = True
        tasks = [task for task in (self._producer_task, self._monitor_task) if task is not None]
        self._producer_task = None
        self._monitor_task = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

        try:
            async with self._control_lock:
                if self._started:
                    await self._run_control(self._close_camera)
        finally:
            self._started = False
            async with self._frame_condition:
                self._frame_condition.notify_all()

    async def capture_still(self, output_path: Path) -> None:
        if not self._started:
            raise RuntimeError("Picamera2 camera service is not running")
        await asyncio.to_thread(self._capture_still, output_path)

    @property
    def motion_enabled(self) -> bool:
        return self._motion_enabled

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        last_activity = self._last_frame_monotonic
        if last_activity is None:
            last_activity = self._started_at
        stale = self._frame_error or (
            last_activity is not None
            and now - last_activity > max(3, 3 / self.settings.live_stream_fps)
        )
        stream_state = "stale" if stale else (
            "starting" if self._last_frame_at is None else "streaming"
        )
        error = self._recording_error or ("Live frame unavailable" if stale else None)
        if error is not None:
            state = "error"
        elif self._recording is not None:
            state = "recording"
        elif not self._motion_enabled:
            state = "disabled"
        elif now - self._last_recording_finished_at < self.settings.motion_cooldown_seconds:
            state = "cooldown"
        else:
            state = "waiting"
        return {
            "enabled": self._motion_enabled,
            "state": state,
            "stream_state": stream_state,
            "last_frame_at": self._last_frame_at,
            "error": error,
            "analysis": self._motion_analysis if self._motion_enabled else None,
            "last_recording_trigger": self._last_recording_trigger,
        }

    async def _run_control(self, operation: Callable[..., Any], *args: Any) -> Any:
        # Cancellation must not release the control lock while its thread still mutates the camera.
        task = asyncio.create_task(asyncio.to_thread(operation, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def set_motion_enabled(self, enabled: bool) -> bool:
        async with self._control_lock:
            if self._stopping:
                raise RuntimeError("Camera is stopping")
            await self._run_control(self._save_motion_enabled, enabled)
            self._motion_enabled = enabled
            self._previous_luma = None
            self._motion_frames = 0
            self._tile_motion_frames = {}
            self._motion_analysis = None
            self._motion_settling_until = 0.0
            if not enabled and self._recording is not None:
                try:
                    await self._run_control(self._finish_recording, True)
                except Exception as exc:
                    self._recording_error = "Recording stop failed"
                    raise RuntimeError("Recording stop failed") from exc
            self._recording_error = None
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
                luma, jpeg = await self._run_control(self._capture_live_frame)
                self._last_frame_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._last_frame_monotonic = time.monotonic()
                self._frame_error = False
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
                self._frame_error = True
                LOGGER.exception("Picamera2 live frame capture failed")
                await asyncio.sleep(1)
                continue

            await asyncio.sleep(max(0, interval - (time.monotonic() - started_at)))

    async def _monitor_recording(self) -> None:
        # This task remains active when frame capture fails or waits on hardware.
        while True:
            try:
                await self._check_recording()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._recording_error = "Recording stop failed"
                LOGGER.exception("Recording monitor failed")
            await asyncio.sleep(0.5)

    async def _check_recording(self) -> None:
        async with self._control_lock:
            recording = self._recording
            if recording is None:
                return
            now = time.monotonic()
            if not self._motion_enabled:
                await self._run_control(self._finish_recording, True)
            elif (
                now >= min(recording.deadline, recording.maximum_deadline)
                or self.status()["stream_state"] == "stale"
            ):
                await self._run_control(self._finish_recording)
            elif not await self._run_control(
                self.video_store.has_recording_space, recording.temporary_path
            ):
                self._recording_error = "Video storage is full"
                await self._run_control(self._finish_recording)

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
        now = time.monotonic()
        if previous_luma is None or len(previous_luma) != len(current_luma):
            self._motion_frames = 0
            self._tile_motion_frames = {}
            self._motion_analysis = None
            self._motion_settling_until = now + self.settings.motion_settle_seconds
            return False

        # Sample both axes. At 640x360 this is 14,400 samples, with no extra
        # camera capture, image encoding, NumPy dependency, or disk writes.
        width = self.settings.live_stream_width
        height = len(current_luma) // width
        shift = estimate_frame_shift(current_luma, previous_luma, width)
        sampler = ShiftedLuma(width, shift.x, shift.y)
        shifted = shift.x != 0 or shift.y != 0
        tile_size = self.settings.motion_analysis_tile_size
        differences: list[tuple[int, int, int]] = []
        histogram = [0] * 511
        brightened_pixels = 0
        darkened_pixels = 0
        raw_sample_count = 0
        for y in range(0, height - 1, MOTION_SAMPLE_STRIDE):
            for x in range(0, width - 1, MOTION_SAMPLE_STRIDE):
                index = y * width + x
                value = smooth_luma(current_luma, index, width)
                raw_difference = value - smooth_luma(previous_luma, index, width)
                raw_sample_count += 1
                if raw_difference >= self.settings.motion_threshold:
                    brightened_pixels += 1
                elif raw_difference <= -self.settings.motion_threshold:
                    darkened_pixels += 1
                if shifted:
                    # Newly visible image edges have no reference; never compare
                    # against wrapped rows or pad them with invented dark pixels.
                    if (x + sampler.left < 0 or x + sampler.right >= width
                            or y + sampler.top < 0 or y + sampler.bottom >= height):
                        continue
                    difference = value - sampler.sample(previous_luma, index)
                else:
                    difference = raw_difference
                differences.append((x, y, difference))
                histogram[difference + 255] += 1
        sample_count = len(differences)
        if not sample_count:
            self._motion_frames = 0
            self._tile_motion_frames = {}
            self._motion_analysis = None
            return False

        # A median shift models exposure/flicker without letting a small moving
        # object change the background estimate. Use raw differences for the
        # existing large illumination-change guard.
        cumulative = 0
        brightness_shift = 0
        for index, count in enumerate(histogram):
            cumulative += count
            if cumulative > sample_count // 2:
                brightness_shift = index - 255
                break
        changed_pixels = brightened_pixels + darkened_pixels
        changed_ratio = changed_pixels / raw_sample_count
        directional_ratio = (
            max(brightened_pixels, darkened_pixels) / changed_pixels if changed_pixels else 0.0
        )
        tile_sample_counts: dict[tuple[int, int], int] = {}
        tile_changed_counts: dict[tuple[int, int], int] = {}
        for x, y, difference in differences:
            tile = (x // tile_size, y // tile_size)
            tile_sample_counts[tile] = tile_sample_counts.get(tile, 0) + 1
            # Compensation only suppresses candidates; it must not turn two
            # opposite sub-threshold flickers into a new motion candidate.
            if (
                abs(difference) >= self.settings.motion_threshold
                and abs(difference - brightness_shift) >= self.settings.motion_threshold
            ):
                tile_changed_counts[tile] = tile_changed_counts.get(tile, 0) + 1

        ratios = {
            tile: count / tile_sample_counts[tile] for tile, count in tile_changed_counts.items()
        }
        candidates = {
            tile: ratio for tile, ratio in ratios.items()
            if ratio >= self.settings.motion_min_changed_ratio
        }
        if (
            changed_ratio >= self.settings.motion_illumination_changed_ratio
            and directional_ratio >= self.settings.motion_illumination_direction_ratio
        ):
            self._motion_settling_until = now + self.settings.motion_settle_seconds
            reason = "illumination"
        elif now < self._motion_settling_until:
            reason = "settling"
        else:
            reason = "candidate" if candidates else ("camera_motion" if shifted else "still")

        self._tile_motion_frames = (
            {
                tile: min(
                    self._tile_motion_frames.get(tile, 0) + 1,
                    self.settings.motion_minimum_consecutive_frames,
                )
                for tile in candidates
            }
            if reason == "candidate" else {}
        )
        self._motion_frames = max(self._tile_motion_frames.values(), default=0)
        detected = self._motion_frames >= self.settings.motion_minimum_consecutive_frames
        if detected:
            reason = "motion"
        self._motion_analysis = {
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "width": width,
            "height": self.settings.live_stream_height,
            "tile_size": tile_size,
            "reason": reason,
            "brightness_shift": brightness_shift,
            "camera_shift_x": shift.x,
            "camera_shift_y": shift.y,
            "camera_shift_support": shift.support,
            "raw_changed_ratio": changed_ratio,
            "largest_tile_changed_ratio": max(ratios.values(), default=0.0),
            "threshold": self.settings.motion_threshold,
            "min_changed_ratio": self.settings.motion_min_changed_ratio,
            "consecutive_frames": self._motion_frames,
            "required_frames": self.settings.motion_minimum_consecutive_frames,
            "tiles": [
                {
                    "x": tile[0] * tile_size,
                    "y": tile[1] * tile_size,
                    "changed_ratio": ratio,
                    "confirmed": self._tile_motion_frames.get(tile, 0)
                    >= self.settings.motion_minimum_consecutive_frames,
                }
                for tile, ratio in candidates.items()
            ],
        }
        return detected

    async def _update_recording(self, motion_detected: bool) -> None:
        async with self._control_lock:
            if not self._motion_enabled or self._stopping:
                return
            try:
                await self._update_recording_locked(motion_detected)
            except VideoStorageFullError:
                self._recording_error = "Video storage is full"
                self._last_recording_finished_at = time.monotonic()
            except Exception:
                self._recording_error = "Recording failed"
                self._last_recording_finished_at = time.monotonic()
                LOGGER.exception("Motion recording failed")

    async def _update_recording_locked(self, motion_detected: bool) -> None:
        now = time.monotonic()
        recording = self._recording
        if recording is not None:
            if now >= recording.maximum_deadline:
                await self._run_control(self._finish_recording)
            elif motion_detected:
                recording.deadline = min(
                    now + self.settings.motion_record_seconds,
                    recording.maximum_deadline,
                )
            elif now >= recording.deadline:
                await self._run_control(self._finish_recording)
            return

        if (
            motion_detected
            and now - self._last_recording_finished_at >= self.settings.motion_cooldown_seconds
        ):
            trigger = self._motion_analysis
            await self._run_control(self._start_recording, now)
            self._last_recording_trigger = trigger
            if trigger is not None:
                LOGGER.info(
                    "Motion recording started: changed_tile=%.3f brightness_shift=%s frames=%s "
                    "camera_shift=(%.1f,%.1f) support=%.2f",
                    trigger["largest_tile_changed_ratio"], trigger["brightness_shift"],
                    trigger["consecutive_frames"],
                    trigger["camera_shift_x"], trigger["camera_shift_y"],
                    trigger["camera_shift_support"],
                )
            self._recording_error = None

    def _start_recording(self, now: float) -> None:
        # Include a margin for container overhead; the monitor also checks actual disk usage.
        expected_bytes = int(
            self.settings.video_bitrate * self.settings.motion_max_record_seconds / 8 * 1.1
        )
        self.video_store.prepare_recording(expected_bytes)
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
        # Keep the encoder reference if stop fails so the monitor can retry it.
        with self._camera_lock:
            if self._recording_encoder is not None:
                camera.stop_encoder(self._recording_encoder)
        try:
            final_path = self.video_store.path_for_new_video(recording.video_id)
            duration_seconds = time.monotonic() - recording.started_at
            if (
                not discard
                and duration_seconds >= self.settings.motion_min_record_seconds
                and recording.temporary_path.is_file()
                and recording.temporary_path.stat().st_size > 0
            ):
                recording.temporary_path.replace(final_path)
                try:
                    self.video_store.set_duration(recording.video_id, duration_seconds)
                finally:
                    # A metadata write failure must not skip retention on a nearly full disk.
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
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            LOGGER.warning("Unable to read motion detection state: %s", exc)
            return False

        enabled = state.get("enabled") if isinstance(state, dict) else None
        if isinstance(enabled, bool):
            return enabled
        LOGGER.warning("Motion detection state is invalid; disabling motion detection")
        return False

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
