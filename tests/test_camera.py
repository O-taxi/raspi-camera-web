import asyncio
import threading
import time
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
from app.services.picamera2 import MOTION_SAMPLE_STRIDE, Picamera2Service, _Recording
from app.services.videos import VideoStore


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


def test_finishing_recording_keeps_camera_running(settings, tmp_path: Path) -> None:
    video_store = VideoStore(tmp_path / "videos", 3)
    service = Picamera2Service(settings, video_store)
    video_id = "20260923-120000-12345678"
    temporary_path = video_store.path_for_recording(video_id)
    temporary_path.write_bytes(b"video")
    encoder = object()

    class Camera:
        def __init__(self) -> None:
            self.stop_encoder_calls: list[object] = []
            self.stop_called = False

        def stop_encoder(self, recording_encoder: object) -> None:
            self.stop_encoder_calls.append(recording_encoder)

        def stop(self) -> None:
            self.stop_called = True

    camera = Camera()
    service._camera = camera
    service._recording = _Recording(
        video_id,
        temporary_path,
        started_at=0.0,
        deadline=0.0,
        maximum_deadline=0.0,
    )
    service._recording_encoder = encoder

    service._finish_recording()

    assert camera.stop_encoder_calls == [encoder]
    assert not camera.stop_called
    assert video_store.path_for_new_video(video_id).is_file()


@pytest.mark.asyncio
async def test_motion_detection_setting_is_persisted(settings, tmp_path: Path) -> None:
    motion_settings = replace(settings, motion_state_path=tmp_path / ".motion-state.json")
    video_store = VideoStore(tmp_path / "videos", 3)
    service = Picamera2Service(motion_settings, video_store)

    enabled = await service.set_motion_enabled(False)

    assert not enabled
    assert motion_settings.motion_state_path.read_text(encoding="utf-8") == '{"enabled": false}\n'
    restored_service = Picamera2Service(
        motion_settings,
        video_store,
    )
    assert not restored_service._load_motion_enabled()


@pytest.mark.asyncio
async def test_disabling_motion_discards_an_active_recording(settings, tmp_path: Path) -> None:
    motion_settings = replace(
        settings,
        motion_state_path=tmp_path / ".motion-state.json",
        motion_min_record_seconds=2,
    )
    video_store = VideoStore(tmp_path / "videos", 3)
    service = Picamera2Service(motion_settings, video_store)
    video_id = "20260923-120000-12345678"
    temporary_path = video_store.path_for_recording(video_id)
    temporary_path.write_bytes(b"video")

    class Camera:
        def stop_encoder(self, _encoder: object) -> None:
            pass

    service._camera = Camera()
    service._recording = _Recording(
        video_id,
        temporary_path,
        started_at=90.0,
        deadline=120.0,
        maximum_deadline=160.0,
    )
    service._recording_encoder = object()

    with patch("app.services.picamera2.time.monotonic", return_value=101.0):
        await service.set_motion_enabled(False)

    assert video_store.resolve(video_id) is None
    assert not temporary_path.exists()


@pytest.mark.asyncio
async def test_recording_stops_at_its_absolute_time_limit(settings, tmp_path: Path) -> None:
    video_store = VideoStore(tmp_path / "videos", 3)
    service = Picamera2Service(settings, video_store)
    service._recording = _Recording(
        "20260923-120000-12345678",
        video_store.path_for_recording("20260923-120000-12345678"),
        started_at=0.0,
        deadline=20.0,
        maximum_deadline=10.0,
    )

    with patch("app.services.picamera2.time.monotonic", return_value=10.0), patch.object(
        service, "_finish_recording"
    ) as finish_recording:
        await service._update_recording(motion_detected=True)

    finish_recording.assert_called_once_with()


def test_global_brightness_change_is_not_motion(settings, tmp_path: Path) -> None:
    motion_settings = replace(
        settings,
        live_stream_width=64,
        live_stream_height=64,
        motion_threshold=10.0,
        motion_settle_seconds=5,
    )
    service = Picamera2Service(motion_settings, VideoStore(tmp_path / "videos", 3))
    service._previous_luma = bytes([10]) * (64 * 64)

    with patch("app.services.picamera2.time.monotonic", return_value=100.0):
        detected = service._detect_motion(bytes([100]) * (64 * 64))

    assert not detected
    assert service._motion_settling_until == 105.0
    assert service._motion_frames == 0


def test_local_motion_uses_changed_pixel_ratio(settings, tmp_path: Path) -> None:
    motion_settings = replace(
        settings,
        live_stream_width=64,
        motion_threshold=10.0,
        motion_analysis_tile_size=16,
        motion_min_changed_ratio=0.10,
        motion_minimum_consecutive_frames=1,
    )
    service = Picamera2Service(motion_settings, VideoStore(tmp_path / "videos", 3))
    first_frame = bytes(64 * 64)
    second_frame = bytearray(first_frame)
    for y in range(16):
        for x in range(0, 16, MOTION_SAMPLE_STRIDE):
            second_frame[y * 64 + x] = 20

    service._previous_luma = first_frame
    with patch("app.services.picamera2.time.monotonic", return_value=100.0):
        detected = service._detect_motion(bytes(second_frame))

    assert detected


def test_scattered_pixel_noise_does_not_trigger_motion(settings, tmp_path: Path) -> None:
    motion_settings = replace(
        settings,
        live_stream_width=64,
        motion_threshold=10.0,
        motion_analysis_tile_size=16,
        motion_min_changed_ratio=0.10,
        motion_minimum_consecutive_frames=1,
    )
    service = Picamera2Service(motion_settings, VideoStore(tmp_path / "videos", 3))
    first_frame = bytes(64 * 64)
    noisy_frame = bytearray(first_frame)
    for y in range(0, 64, 16):
        for x in range(0, 64, 16):
            noisy_frame[y * 64 + x] = 20

    service._previous_luma = first_frame
    with patch("app.services.picamera2.time.monotonic", return_value=100.0):
        detected = service._detect_motion(bytes(noisy_frame))

    assert not detected


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_start", [False, True])
async def test_disable_waits_for_pending_recording_start(
    settings, tmp_path: Path, cancel_start: bool
) -> None:
    service = Picamera2Service(
        replace(settings, motion_state_path=tmp_path / "motion.json"),
        VideoStore(tmp_path / "videos", 3),
    )
    starting = threading.Event()
    finish_start = threading.Event()
    video_id = "20260923-120000-12345678"
    temporary_path = service.video_store.path_for_recording(video_id)

    class Camera:
        def stop_encoder(self, _encoder: object) -> None:
            pass

    service._camera = Camera()

    def slow_start(now: float) -> None:
        starting.set()
        assert finish_start.wait(3)
        temporary_path.write_bytes(b"video")
        service._recording_encoder = object()
        service._recording = _Recording(video_id, temporary_path, now, now + 20, now + 60)

    with patch.object(service, "_start_recording", side_effect=slow_start):
        start = asyncio.create_task(service._update_recording(True))
        assert await asyncio.to_thread(starting.wait, 2)
        if cancel_start:
            start.cancel()
        disable = asyncio.create_task(service.set_motion_enabled(False))
        try:
            await asyncio.sleep(0.02)
            assert not disable.done()
        finally:
            finish_start.set()
        await asyncio.gather(start, return_exceptions=True)
        assert not await asyncio.wait_for(disable, 2)
        await service._update_recording(True)

    assert service._recording is None
    assert not temporary_path.exists()
    assert service.video_store.list_videos() == []


@pytest.mark.asyncio
async def test_deadline_monitor_finishes_recording_while_frame_capture_waits(
    settings, tmp_path: Path
) -> None:
    service = Picamera2Service(settings, VideoStore(tmp_path / "videos", 3))
    frame_started = threading.Event()
    release_frame = threading.Event()
    encoder_stopped = threading.Event()
    video_id = "20260923-120000-12345678"
    path = service.video_store.path_for_recording(video_id)
    path.write_bytes(b"video")
    now = time.monotonic()
    service._recording = _Recording(video_id, path, now - 5, now + 20, now + 0.05)
    service._recording_encoder = object()

    class Camera:
        def stop_encoder(self, _encoder: object) -> None:
            encoder_stopped.set()

    service._camera = Camera()

    def slow_frame() -> tuple[bytes, bytes]:
        frame_started.set()
        assert release_frame.wait(3)
        return b"frame", b"jpeg"

    with patch.object(service, "_capture_live_frame", side_effect=slow_frame):
        producer = asyncio.create_task(service._produce_frames())
        monitor = asyncio.create_task(service._monitor_recording())
        try:
            assert await asyncio.to_thread(frame_started.wait, 2)
            assert await asyncio.to_thread(encoder_stopped.wait, 2)
            assert not release_frame.is_set()
        finally:
            producer.cancel()
            monitor.cancel()
            release_frame.set()
            await asyncio.gather(producer, monitor, return_exceptions=True)
    assert service.video_store.resolve(video_id) is not None


@pytest.mark.asyncio
async def test_frame_failure_stops_active_recording(settings, tmp_path: Path) -> None:
    service = Picamera2Service(settings, VideoStore(tmp_path / "videos", 3))
    service._recording = _Recording(
        "20260923-120000-12345678", tmp_path / "video.part.mp4",
        time.monotonic(), time.monotonic() + 20, time.monotonic() + 60,
    )
    with patch.object(service, "_capture_live_frame", side_effect=RuntimeError("camera fault")):
        producer = asyncio.create_task(service._produce_frames())
        try:
            for _ in range(100):
                if service._frame_error:
                    break
                await asyncio.sleep(0.01)
            assert service._frame_error
            with patch.object(service, "_finish_recording") as finish:
                await service._check_recording()
            finish.assert_called_once_with()
            assert service.status()["state"] == "error"
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)


@pytest.mark.parametrize("contents", [b"broken", b'{"enabled": "false"}', b"\xff"])
def test_invalid_saved_motion_state_disables_detection(
    settings, tmp_path: Path, contents: bytes
) -> None:
    state_path = tmp_path / "motion.json"
    state_path.write_bytes(contents)
    service = Picamera2Service(
        replace(settings, motion_enabled=True, motion_state_path=state_path),
        VideoStore(tmp_path / "videos", 3),
    )
    assert not service._load_motion_enabled()


def test_missing_motion_state_uses_environment_default(settings, tmp_path: Path) -> None:
    service = Picamera2Service(
        replace(settings, motion_enabled=True, motion_state_path=tmp_path / "missing.json"),
        VideoStore(tmp_path / "videos", 3),
    )
    assert service._load_motion_enabled()


def test_motion_status_marks_old_frames_stale(settings, tmp_path: Path) -> None:
    service = Picamera2Service(settings, VideoStore(tmp_path / "videos", 3))
    service._last_frame_at = "2026-09-25T01:00:00+00:00"
    service._last_frame_monotonic = time.monotonic() - 10
    assert service.status()["enabled"]
    assert service.status()["stream_state"] == "stale"
    assert service.status()["state"] == "error"


@pytest.mark.asyncio
async def test_storage_pressure_stops_recording_and_reports_error(settings, tmp_path: Path) -> None:
    service = Picamera2Service(settings, VideoStore(tmp_path / "videos", 3))
    now = time.monotonic()
    service._recording = _Recording(
        "20260923-120000-12345678", tmp_path / "video.part.mp4", now, now + 20, now + 60,
    )
    with patch.object(service.video_store, "has_recording_space", return_value=False), patch.object(
        service, "_finish_recording"
    ) as finish:
        await service._check_recording()
    finish.assert_called_once_with()
    assert service.status()["error"] == "Video storage is full"


@pytest.mark.asyncio
async def test_failed_encoder_stop_does_not_report_success(settings, tmp_path: Path) -> None:
    service = Picamera2Service(
        replace(settings, motion_state_path=tmp_path / "motion.json"),
        VideoStore(tmp_path / "videos", 3),
    )
    service._recording = _Recording(
        "20260923-120000-12345678", tmp_path / "video.part.mp4", 0, 20, 60,
    )

    class Camera:
        def stop_encoder(self, _encoder: object) -> None:
            raise RuntimeError("device output must remain private")

    service._camera = Camera()
    service._recording_encoder = object()
    with pytest.raises(RuntimeError, match="Recording stop failed"):
        await service.set_motion_enabled(False)
    assert service._recording is not None
    assert service._recording_encoder is not None
    assert service.status()["state"] == "error"
    assert service.status()["error"] == "Recording stop failed"
