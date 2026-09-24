import math
import random
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.motion import estimate_frame_shift
from app.services.picamera2 import Picamera2Service
from app.services.videos import VideoStore


def textured_frame(
    dx: float = 0, dy: float = 0, *, object_change: int = 0, brightness: int = 0,
    noise_seed: int = 0, width: int = 64, height: int = 64,
) -> bytes:
    rng = random.Random(noise_seed)
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            # Sample the underlying scene at subpixel positions, without wrapping edges.
            sx, sy = x - dx, y - dy
            value = (100 + 25 * math.sin(sx * 0.3) + 20 * math.cos(sy * 0.4)
                     + 15 * math.sin(sx * 0.5 + sy * 0.3) + brightness)
            if 16 <= sx < 32 and 16 <= sy < 32:
                value += object_change
            if noise_seed:
                value += rng.gauss(0, 4)
            pixels.append(max(0, min(255, round(value))))
    return bytes(pixels)


@pytest.fixture
def detector(settings, tmp_path: Path) -> Picamera2Service:
    return Picamera2Service(
        replace(settings, live_stream_width=64, live_stream_height=64,
                motion_minimum_consecutive_frames=2, motion_analysis_tile_size=16),
        VideoStore(tmp_path / "videos", 3),
    )


@pytest.mark.parametrize("dx,dy", [(1, 0), (-1, 1), (0.5, -0.5), (2.5, 1.5), (-3, 3)])
def test_estimates_distributed_camera_translation(dx: float, dy: float) -> None:
    shift = estimate_frame_shift(textured_frame(dx, dy), textured_frame(), 64)
    assert shift.x == dx
    assert shift.y == dy
    assert shift.support >= 0.5


@pytest.mark.asyncio
async def test_shelf_vibration_does_not_start_recording(detector) -> None:
    detector._previous_luma = textured_frame()
    with patch("app.services.picamera2.time.monotonic", return_value=100), patch.object(
        detector, "_start_recording"
    ) as start:
        for dx, dy in [(0.5, -0.5), (-0.5, 0.5), (1, 0), (0, 0)] * 3:
            detected = detector._detect_motion(textured_frame(dx, dy))
            assert not detected
            assert detector.status()["analysis"]["reason"] == "camera_motion"
            assert detector.status()["analysis"]["tiles"] == []
            await detector._update_recording(detected)
    start.assert_not_called()


def test_local_object_motion_is_preserved_while_camera_shakes(detector) -> None:
    detector._previous_luma = textured_frame()
    for index, (dx, dy) in enumerate([(0.5, 0.5), (-0.5, 0), (0, 0.5)]):
        detected = detector._detect_motion(textured_frame(
            dx, dy, object_change=60 if index % 2 == 0 else 0
        ))
        assert detected is (index >= 1)
        analysis = detector.status()["analysis"]
        assert analysis["camera_shift_support"] >= 0.5
        assert any(tile["x"] == 16 and tile["y"] == 16 for tile in analysis["tiles"])


def test_local_object_cannot_be_used_as_camera_reference() -> None:
    def local_frame(left: int) -> bytes:
        result = bytearray([80]) * (64 * 64)
        for y in range(16, 32):
            for x in range(left, left + 16):
                result[y * 64 + x] = 160 if (x - left) % 4 else 20
        return bytes(result)

    shift = estimate_frame_shift(local_frame(18), local_frame(16), 64)
    assert shift.x == shift.y == 0
    assert shift.support == 0


def test_uniform_brightness_change_is_not_camera_translation() -> None:
    shift = estimate_frame_shift(bytes([90]) * 4096, bytes([80]) * 4096, 64)
    assert shift.x == shift.y == shift.support == 0


def test_sensor_noise_does_not_invent_camera_motion(detector) -> None:
    detector._previous_luma = textured_frame(noise_seed=1)
    for seed in range(2, 12):
        assert not detector._detect_motion(textured_frame(noise_seed=seed))
        assert detector.status()["analysis"]["camera_shift_support"] == 0


def test_translation_with_brightness_change_and_sensor_noise(detector) -> None:
    detector._previous_luma = textured_frame(noise_seed=1)
    assert not detector._detect_motion(textured_frame(1, 0.5, brightness=8, noise_seed=2))
    analysis = detector.status()["analysis"]
    assert analysis["camera_shift_x"] == 1
    assert analysis["camera_shift_y"] == 0.5
    assert abs(analysis["brightness_shift"] - 8) <= 1


def test_newly_visible_edges_do_not_trigger_motion(detector) -> None:
    previous = bytes(random.Random(7).randbytes(64 * 64))
    current = bytearray([255]) * (64 * 64)
    for y in range(1, 64):
        current[y * 64 + 1:(y + 1) * 64] = previous[(y - 1) * 64:y * 64 - 1]
    detector._previous_luma = previous
    assert not detector._detect_motion(bytes(current))
    analysis = detector.status()["analysis"]
    assert analysis["camera_shift_x"] == analysis["camera_shift_y"] == 1
    assert analysis["tiles"] == []
