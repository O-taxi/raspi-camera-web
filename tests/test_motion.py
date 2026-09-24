from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.picamera2 import Picamera2Service, _Recording
from app.services.videos import VideoStore


@pytest.fixture
def detector(settings, tmp_path: Path) -> Picamera2Service:
    return Picamera2Service(
        replace(settings, live_stream_width=64, live_stream_height=64,
                motion_analysis_tile_size=16, motion_minimum_consecutive_frames=3),
        VideoStore(tmp_path / "videos", 3),
    )


def frame(background: int = 80, patches: tuple[tuple[int, int, int], ...] = ()) -> bytes:
    result = bytearray([background]) * (64 * 64)
    for left, top, value in patches:
        for y in range(top, top + 16):
            result[y * 64 + left:y * 64 + left + 16] = bytes([value]) * 16
    return bytes(result)


@pytest.mark.parametrize("flicker", [False, True])
@pytest.mark.asyncio
async def test_static_scene_does_not_record_periodically(detector, flicker: bool) -> None:
    # Five minutes at 5 fps, including the reported 90-second recurrence.
    # Weak flicker crosses the old threshold in one tile, but affects the
    # rest of the image by only 8, bypassing the old 65% illumination guard.
    detector._previous_luma = frame()
    with patch("app.services.picamera2.time.monotonic") as clock, patch.object(
        detector, "_start_recording"
    ) as start:
        for index in range(1500):
            clock.return_value = 100.0 + index / 5
            current = frame(88, ((0, 0, 96),)) if flicker and index % 2 else frame()
            detected = detector._detect_motion(current)
            assert not detected
            await detector._update_recording(detected)
    start.assert_not_called()
    assert detector.status()["analysis"]["reason"] == "still"


def test_candidates_in_different_tiles_do_not_accumulate(detector) -> None:
    detector._previous_luma = frame()
    patches = []
    for left in (0, 16, 32, 48):
        patches.append((left, 0, 110))
        assert not detector._detect_motion(frame(patches=tuple(patches)))
        assert detector._motion_frames == 1


def test_compensation_does_not_amplify_opposite_subthreshold_flicker(detector) -> None:
    detector._previous_luma = frame()
    for index in range(10):
        # Raw changes are only +8 and -8, but subtracting the median alone
        # would produce -16 in one tile and create a false candidate.
        current = frame(88, ((0, 0, 72),)) if index % 2 == 0 else frame()
        assert not detector._detect_motion(current)
        assert detector.status()["analysis"]["tiles"] == []


def test_local_motion_survives_brightness_compensation_and_reports_location(detector) -> None:
    detector._previous_luma = frame()
    for index in range(3):
        current = frame(88, ((16, 32, 120),)) if index % 2 == 0 else frame()
        assert detector._detect_motion(current) is (index == 2)
    analysis = detector.status()["analysis"]
    assert analysis["reason"] == "motion"
    assert analysis["brightness_shift"] == 8
    assert analysis["consecutive_frames"] == 3
    assert analysis["tiles"] == [
        {"x": 16, "y": 32, "changed_ratio": 1.0, "confirmed": True}
    ]
    # An unchanged frame resets the spatial history too.
    assert not detector._detect_motion(current)
    assert not detector._detect_motion(frame())
    assert detector._motion_frames == 1


def test_startup_and_illumination_change_require_settling(detector) -> None:
    with patch("app.services.picamera2.time.monotonic") as clock:
        clock.return_value = 100.0
        assert not detector._detect_motion(frame())
        clock.return_value = 101.0
        assert not detector._detect_motion(frame(patches=((0, 0, 110),)))
        assert detector.status()["analysis"]["reason"] == "settling"
        clock.return_value = 106.0
        assert not detector._detect_motion(frame(160))
        assert detector.status()["analysis"]["reason"] == "illumination"
        clock.return_value = 107.0
        assert not detector._detect_motion(frame(160, ((0, 0, 190),)))
        assert detector.status()["analysis"]["reason"] == "settling"
        for index in range(3):
            clock.return_value = 112.0 + index
            current = frame(160) if index % 2 == 0 else frame(160, ((0, 0, 190),))
            assert detector._detect_motion(current) is (index == 2)


@pytest.mark.asyncio
async def test_recording_limit_and_cooldown_require_new_detection(detector) -> None:
    starts = []

    def start(now: float) -> None:
        starts.append(now)
        detector._recording = _Recording(
            "20260925-120000-12345678", Path("unused.part.mp4"), now, now + 20, now + 60
        )

    def finish() -> None:
        detector._recording = None
        detector._last_recording_finished_at = clock.return_value

    with patch("app.services.picamera2.time.monotonic") as clock, patch.object(
        detector, "_start_recording", side_effect=start
    ), patch.object(detector, "_finish_recording", side_effect=finish):
        # Continuous detections reproduce 60 seconds recording + 30 seconds cooldown.
        for second in range(100, 191):
            clock.return_value = float(second)
            await detector._update_recording(True)
        assert starts == [100.0, 190.0]
        # Once detection stops, the tail expires and no timer starts another recording.
        for second in range(191, 401):
            clock.return_value = float(second)
            await detector._update_recording(False)
        assert detector._recording is None
        assert starts == [100.0, 190.0]


@pytest.mark.asyncio
async def test_recording_trigger_is_retained_after_motion_disappears(detector) -> None:
    detector._previous_luma = frame()
    with patch("app.services.picamera2.time.monotonic", return_value=100.0), patch.object(
        detector, "_start_recording"
    ):
        for index in range(3):
            current = frame(patches=((16, 16, 110),)) if index % 2 == 0 else frame()
            detected = detector._detect_motion(current)
        await detector._update_recording(detected)
    detector._detect_motion(current)
    status = detector.status()
    assert status["analysis"]["reason"] == "still"
    assert status["last_recording_trigger"]["reason"] == "motion"
    assert status["last_recording_trigger"]["tiles"][0]["x"] == 16


@pytest.mark.asyncio
async def test_toggle_resets_candidate_history(detector, tmp_path: Path) -> None:
    detector.settings = replace(detector.settings, motion_state_path=tmp_path / "state.json")
    detector._previous_luma = frame()
    detector._detect_motion(frame(patches=((16, 16, 110),)))
    await detector.set_motion_enabled(False)
    assert detector.status()["analysis"] is None
    assert detector._tile_motion_frames == {}
    await detector.set_motion_enabled(True)
    assert not detector._detect_motion(frame())
