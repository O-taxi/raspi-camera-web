import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from app.main import create_app
from app.services.camera import CameraService
from app.services.photos import PhotoStore
from app.services.videos import VideoStore


@dataclass(frozen=True)
class AsgiResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]

    def json(self) -> Any:
        return json.loads(self.content)


async def asgi_request(
    application: FastAPI,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> AsgiResponse:
    messages: list[dict[str, Any]] = []
    request_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)
        if message["type"] == "http.response.pathsend":
            messages.append(
                {"type": "http.response.body", "body": Path(message["path"]).read_bytes()}
            )

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "extensions": {"http.response.pathsend": {}},
        "headers": [
            (name.lower().encode("ascii"), value.encode("ascii"))
            for name, value in (headers or {}).items()
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    await application(scope, receive, send)
    status = next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    )
    content = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    response_headers = {
        name.decode("latin-1"): value.decode("latin-1")
        for message in messages
        if message["type"] == "http.response.start"
        for name, value in message.get("headers", [])
    }
    return AsgiResponse(status_code=status, content=content, headers=response_headers)


@pytest.mark.asyncio
async def test_capture_and_retrieve_photo(settings) -> None:
    async def capture(path: Path) -> None:
        path.write_bytes(b"jpeg")

    store = PhotoStore(settings.photo_dir, settings.maximum_photos)
    camera = CameraService(settings, store, capture)
    application = create_app(settings, camera)

    response = await asgi_request(application, "POST", "/api/capture")
    image_response = await asgi_request(application, "GET", response.json()["url"])

    assert response.status_code == 200
    assert response.headers["x-capture-cooldown"] == "1"
    payload = response.json()
    assert payload["url"].startswith("/photos/")
    assert image_response.content == b"jpeg"


@pytest.mark.asyncio
async def test_capture_rate_limit_returns_retry_after(settings) -> None:
    async def capture(path: Path) -> None:
        path.write_bytes(b"jpeg")

    store = PhotoStore(settings.photo_dir, settings.maximum_photos)
    camera = CameraService(settings, store, capture)
    application = create_app(settings, camera)
    await asgi_request(application, "POST", "/api/capture")

    response = await asgi_request(application, "POST", "/api/capture")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"


@pytest.mark.asyncio
async def test_photo_route_rejects_path_traversal(settings) -> None:
    response = await asgi_request(create_app(settings), "GET", "/photos/not-a-photo")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_capture_rejects_cross_site_browser_request(settings) -> None:
    response = await asgi_request(
        create_app(settings),
        "POST",
        "/api/capture",
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_photo(settings) -> None:
    store = PhotoStore(settings.photo_dir, settings.maximum_photos)
    photo_id = "20260920-120000-00000001"
    store.path_for_new_photo(photo_id).write_bytes(b"jpeg")
    application = create_app(settings)

    response = await asgi_request(application, "DELETE", f"/api/photos/{photo_id}")

    assert response.status_code == 204
    assert store.resolve(photo_id) is None


@pytest.mark.asyncio
async def test_delete_photo_rejects_invalid_or_missing_id(settings) -> None:
    application = create_app(settings)

    response = await asgi_request(application, "DELETE", "/api/photos/not-a-photo")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_photo_rejects_cross_site_request(settings) -> None:
    application = create_app(settings)

    response = await asgi_request(
        application,
        "DELETE",
        "/api/photos/20260920-120000-00000001",
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_and_download_recorded_videos(settings, tmp_path: Path) -> None:
    video_settings = replace(
        settings,
        camera_backend="picamera2",
        video_dir=tmp_path / "videos",
    )
    store = VideoStore(video_settings.video_dir, video_settings.maximum_videos)
    video_id = "20260923-120000-12345678"
    store.path_for_new_video(video_id).write_bytes(b"mp4")
    application = create_app(video_settings)

    list_response = await asgi_request(application, "GET", "/api/videos")
    download_response = await asgi_request(application, "GET", f"/videos/{video_id}")

    assert list_response.status_code == 200
    videos = list_response.json()
    assert len(videos) == 1
    assert videos[0]["id"] == video_id
    assert videos[0]["url"] == f"/videos/{video_id}"
    assert download_response.status_code == 200
    assert download_response.content == b"mp4"
    assert f'filename="{video_id}.mp4"' in download_response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_motion_detection_can_be_remotely_disabled(settings, tmp_path: Path) -> None:
    video_settings = replace(
        settings,
        camera_backend="picamera2",
        video_dir=tmp_path / "videos",
        motion_state_path=tmp_path / "videos" / ".motion-state.json",
    )
    application = create_app(video_settings)

    status_response = await asgi_request(application, "GET", "/api/motion")
    update_response = await asgi_request(
        application,
        "PUT",
        "/api/motion",
        headers={"Content-Type": "application/json"},
        body=b'{"enabled": false}',
    )

    assert status_response.status_code == 200
    assert status_response.json() == {"enabled": True}
    assert update_response.status_code == 200
    assert update_response.json() == {"enabled": False}
    assert video_settings.motion_state_path.is_file()
