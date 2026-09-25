import asyncio
import json
import struct
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg
import numpy as np
import pytest
from PIL import Image

from app.main import create_app
from app.services.orientation import set_mp4_rotation
from app.services.picamera2 import Picamera2Service, _Recording
from app.services.videos import VideoStore
from tests.test_routes import asgi_request


def box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def mp4_file(path: Path, *, version: int = 0, audio: bool = False) -> int:
    matrix = struct.pack(">9i", 1 << 16, 0, 0, 0, 1 << 16, 0, 0, 0, 1 << 30)
    header = bytes([version]) + bytes(51 if version else 39)
    track_header = box(b"tkhd", header + matrix + struct.pack(">II", 64 << 16, 32 << 16))
    media = box(b"mdia", box(b"hdlr", bytes(8) + (b"soun" if audio else b"vide") + bytes(4)))
    track = box(b"trak", track_header + media)
    contents = box(b"ftyp", b"isom0000") + box(b"mdat", b"video payload") + box(b"moov", track)
    path.write_bytes(contents)
    return contents.index(matrix)


@pytest.mark.parametrize("degrees,matrix", [
    (90, (0, 1, 0, -1, 0, 0, 32, 0, 1)),
    (180, (-1, 0, 0, 0, -1, 0, 64, 32, 1)),
    (270, (0, -1, 0, 1, 0, 0, 0, 64, 1)),
])
@pytest.mark.parametrize("version", [0, 1])
def test_mp4_rotation_updates_only_track_matrix(
    tmp_path: Path, degrees: int, matrix: tuple[int, ...], version: int
) -> None:
    path = tmp_path / "recording.part.mp4"
    offset = mp4_file(path, version=version)
    before = path.read_bytes()
    set_mp4_rotation(path, degrees)
    after = path.read_bytes()
    expected = struct.pack(">9i", *(value * (1 << 30) if index == 8 else value * (1 << 16)
                                     for index, value in enumerate(matrix)))
    assert after == before[:offset] + expected + before[offset + 36:]


def test_mp4_rotation_rejects_invalid_video_without_modifying_it(tmp_path: Path) -> None:
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"not an MP4")
    with pytest.raises(ValueError):
        set_mp4_rotation(path, 90)
    assert path.read_bytes() == b"not an MP4"
    offset = mp4_file(path, audio=True)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="video track"):
        set_mp4_rotation(path, 90)
    assert path.read_bytes()[offset:offset + 36] == before[offset:offset + 36]


@pytest.mark.parametrize("degrees", [90, 180, 270])
def test_ffmpeg_decodes_mp4_in_requested_orientation(tmp_path: Path, degrees: int) -> None:
    image = Image.new("RGB", (64, 32), "red")
    image.paste("blue", (32, 0, 64, 32))
    path = tmp_path / "video.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    encoded = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "rawvideo",
         "-pixel_format", "rgb24", "-video_size", "64x32", "-framerate", "1", "-i", "-",
         "-frames:v", "1", "-c:v", "mpeg4", "-y", str(path)],
        input=image.tobytes(), capture_output=True, check=True, timeout=20,
    )
    assert not encoded.stderr
    set_mp4_rotation(path, degrees)
    decoded = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=20,
    )
    size = (32, 64) if degrees in (90, 270) else (64, 32)
    rotated = Image.frombytes("RGB", size, decoded.stdout)
    if degrees == 90:
        assert rotated.getpixel((5, 5))[0] > 200
        assert rotated.getpixel((5, 59))[2] > 200
    elif degrees == 180:
        assert rotated.getpixel((5, 5))[2] > 200
        assert rotated.getpixel((59, 5))[0] > 200
    else:
        assert rotated.getpixel((5, 5))[2] > 200
        assert rotated.getpixel((5, 59))[0] > 200


def test_finished_recording_uses_rotation_at_recording_start(settings, tmp_path: Path) -> None:
    video_store = VideoStore(tmp_path / "videos", 3, minimum_free_bytes=0)
    service = Picamera2Service(replace(settings, motion_min_record_seconds=0), video_store)
    video_id = "20260925-120000-12345678"
    temporary_path = video_store.path_for_recording(video_id)
    matrix_offset = mp4_file(temporary_path)

    class Camera:
        def stop_encoder(self, encoder: object) -> None:
            assert encoder is service._recording_encoder

    service._camera = Camera()
    service._recording_encoder = object()
    service._recording = _Recording(video_id, temporary_path, 1, 20, 60, 90)
    service._rotation_degrees = 180
    with patch("app.services.picamera2.time.monotonic", return_value=10):
        service._finish_recording()

    saved_path = video_store.path_for_new_video(video_id)
    assert saved_path.is_file()
    assert not temporary_path.exists()
    assert struct.unpack(">9i", saved_path.read_bytes()[matrix_offset:matrix_offset + 36]) == (
        0, 1 << 16, 0, -(1 << 16), 0, 0, 32 << 16, 0, 1 << 30
    )


@pytest.mark.asyncio
async def test_rotation_persists_and_is_reloaded_at_start(settings, tmp_path: Path) -> None:
    state_path = tmp_path / "videos" / ".rotation-state.json"
    service_settings = replace(settings, rotation_state_path=state_path)
    service = Picamera2Service(service_settings, VideoStore(tmp_path / "videos", 3))
    for degrees in (90, 180, 270, 0, 90):
        assert await service.set_rotation(degrees) == degrees
        assert service.status()["rotation_degrees"] == degrees
    assert json.loads(state_path.read_text()) == {"degrees": 90}
    restored = Picamera2Service(service_settings, VideoStore(tmp_path / "videos", 3))

    class Camera:
        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    async def idle() -> None:
        await asyncio.Event().wait()

    def open_camera() -> None:
        restored._camera = Camera()

    with patch.object(restored, "_open_camera", side_effect=open_camera), \
         patch.object(restored, "_produce_frames", side_effect=idle), \
         patch.object(restored, "_monitor_recording", side_effect=idle):
        await restored.start()
        assert restored.status()["rotation_degrees"] == 90
        await restored.stop()


@pytest.mark.parametrize("invalid", ["broken", "{\"degrees\": 45}", "{\"degrees\": true}"])
def test_invalid_rotation_state_uses_zero(settings, tmp_path: Path, invalid: str) -> None:
    state_path = tmp_path / "rotation.json"
    state_path.write_text(invalid)
    service = Picamera2Service(replace(settings, rotation_state_path=state_path),
                               VideoStore(tmp_path / "videos", 3))
    assert service._load_rotation() == 0


@pytest.mark.asyncio
async def test_cannot_rotate_during_recording(settings, tmp_path: Path) -> None:
    state_path = tmp_path / "rotation.json"
    service = Picamera2Service(replace(settings, rotation_state_path=state_path),
                               VideoStore(tmp_path / "videos", 3))
    service._recording = _Recording("20260925-120000-12345678", tmp_path / "part.mp4", 0, 20, 60)
    with pytest.raises(RuntimeError):
        await service.set_rotation(90)
    assert service.status()["rotation_degrees"] == 0
    assert not state_path.exists()


@pytest.mark.parametrize("degrees,expected", [(0, (40, 20)), (90, (20, 40)),
                                              (180, (40, 20)), (270, (20, 40))])
def test_new_photo_pixels_are_rotated(settings, tmp_path: Path, degrees: int,
                                      expected: tuple[int, int]) -> None:
    service = Picamera2Service(settings, VideoStore(tmp_path / "videos", 3))

    class Camera:
        def capture_file(self, path: str, name: str) -> None:
            assert name == "main"
            image = Image.new("RGB", (40, 20), "red")
            image.paste("blue", (20, 0, 40, 20))
            image.save(path, format="JPEG")

    service._camera = Camera()
    service._rotation_degrees = degrees
    output = tmp_path / "photo.jpg"
    service._capture_still(output)
    with Image.open(output) as saved:
        assert saved.size == expected
        if degrees == 90:
            assert saved.getpixel((5, 5))[0] > saved.getpixel((5, 35))[0]
        elif degrees == 270:
            assert saved.getpixel((5, 5))[2] > saved.getpixel((5, 35))[2]


@pytest.mark.parametrize("degrees,expected", [(0, (8, 4)), (90, (4, 8)),
                                              (180, (8, 4)), (270, (4, 8))])
def test_live_jpeg_rotates_but_motion_luma_stays_native(settings, tmp_path: Path,
                                                         degrees: int,
                                                         expected: tuple[int, int]) -> None:
    service = Picamera2Service(replace(settings, live_stream_width=8, live_stream_height=4),
                               VideoStore(tmp_path / "videos", 3))
    service._rotation_degrees = degrees
    frame = np.full((6, 8), 128, dtype=np.uint8)
    frame[:4, :4] = 30
    frame[:4, 4:] = 220
    luma, jpeg = service._encode_live_frame(frame)
    assert luma == frame[:4].tobytes()
    from io import BytesIO

    with Image.open(BytesIO(jpeg)) as image:
        assert image.size == expected
        if degrees == 90:
            assert image.getpixel((2, 1))[0] < image.getpixel((2, 6))[0]


@pytest.mark.asyncio
async def test_rotation_api_validates_and_reports_conflicts(settings, tmp_path: Path) -> None:
    service_settings = replace(settings, camera_backend="picamera2",
                               video_dir=tmp_path / "videos",
                               rotation_state_path=tmp_path / "videos" / ".rotation-state.json")
    application = create_app(service_settings)
    first = await asgi_request(application, "GET", "/api/motion")
    updated = await asgi_request(application, "PUT", "/api/rotation",
                                 headers={"Content-Type": "application/json"},
                                 body=b'{"degrees":90}')
    invalid = await asgi_request(application, "PUT", "/api/rotation",
                                 headers={"Content-Type": "application/json"},
                                 body=b'{"degrees":45}')
    cross_site = await asgi_request(application, "PUT", "/api/rotation",
                                    headers={"Content-Type": "application/json",
                                             "Sec-Fetch-Site": "cross-site"},
                                    body=b'{"degrees":180}')
    assert first.json()["rotation_degrees"] == 0
    assert updated.json() == {"degrees": 90}
    assert invalid.status_code == 422
    assert cross_site.status_code == 403
    assert (await asgi_request(application, "GET", "/api/motion")).json()["rotation_degrees"] == 90
    application.state.video_service._recording = _Recording(
        "20260925-120000-12345678", tmp_path / "part.mp4", 0, 20, 60
    )
    busy = await asgi_request(application, "PUT", "/api/rotation",
                              headers={"Content-Type": "application/json"},
                              body=b'{"degrees":180}')
    assert busy.status_code == 409
    assert application.state.video_service.status()["rotation_degrees"] == 90
