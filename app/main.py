from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import Settings
from app.services.camera import (
    CameraBusyError,
    CameraCaptureError,
    CameraService,
    CameraTimeoutError,
)
from app.services.photos import PhotoStore
from app.services.picamera2 import MJPEG_BOUNDARY, Picamera2Service
from app.services.videos import VideoStore

APP_DIR = Path(__file__).resolve().parent


class PhotoResponse(BaseModel):
    id: str
    captured_at: str
    url: str


class ErrorResponse(BaseModel):
    detail: str


class VideoResponse(BaseModel):
    id: str
    captured_at: str
    url: str
    duration_seconds: int | None


class MotionStatusResponse(BaseModel):
    enabled: bool
    state: Literal["disabled", "waiting", "recording", "cooldown", "error"]
    stream_state: Literal["starting", "streaming", "stale"]
    last_frame_at: str | None
    error: str | None


class MotionSettingsRequest(BaseModel):
    enabled: bool


def create_app(
    settings: Settings | None = None,
    camera_service: CameraService | None = None,
) -> FastAPI:
    active_settings = settings or Settings.from_environment()
    store = PhotoStore(active_settings.photo_dir, active_settings.maximum_photos)
    video_store: VideoStore | None = None
    video_service: Picamera2Service | None = None
    if active_settings.camera_backend == "picamera2":
        video_store = VideoStore(
            active_settings.video_dir,
            active_settings.maximum_videos,
            active_settings.maximum_video_bytes,
            active_settings.minimum_free_disk_bytes,
        )
        video_service = Picamera2Service(active_settings, video_store)
    camera = camera_service or CameraService(
        active_settings,
        store,
        video_service.capture_still if video_service is not None else None,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if video_service is not None:
            await video_service.start()
        try:
            yield
        finally:
            if video_service is not None:
                await video_service.stop()

    templates = Jinja2Templates(directory=APP_DIR / "templates")

    application = FastAPI(title="raspi-camera-web", version="0.1.0", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    application.state.photo_store = store
    application.state.camera_service = camera
    application.state.video_store = video_store
    application.state.video_service = video_service

    @application.get("/", include_in_schema=False)
    async def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"live_stream_available": video_service is not None},
        )

    @application.post(
        "/api/capture",
        response_model=PhotoResponse,
        responses={429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    async def capture(request: Request, response: Response) -> PhotoResponse:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site capture is not allowed")
        try:
            photo = await application.state.camera_service.capture()
        except CameraBusyError as exc:
            raise HTTPException(
                status_code=429,
                detail=str(exc),
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc
        except CameraTimeoutError as exc:
            raise HTTPException(
                status_code=503,
                detail="Camera capture timed out",
                headers={
                    "Retry-After": str(active_settings.minimum_capture_interval_seconds)
                },
            ) from exc
        except CameraCaptureError as exc:
            raise HTTPException(
                status_code=503,
                detail="Camera capture failed",
                headers={
                    "Retry-After": str(active_settings.minimum_capture_interval_seconds)
                },
            ) from exc
        response.headers["X-Capture-Cooldown"] = str(
            active_settings.minimum_capture_interval_seconds
        )
        return PhotoResponse(**asdict(photo))

    @application.get("/api/photos", response_model=list[PhotoResponse])
    async def photos() -> list[PhotoResponse]:
        return [PhotoResponse(**asdict(photo)) for photo in store.list_photos()]

    @application.delete(
        "/api/photos/{photo_id}",
        status_code=204,
        response_class=Response,
        responses={404: {"model": ErrorResponse}},
    )
    async def delete_photo(photo_id: str, request: Request) -> Response:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site deletion is not allowed")
        if not store.delete(photo_id):
            raise HTTPException(status_code=404, detail="Photo not found")
        return Response(status_code=204)

    @application.get("/photos/{photo_id}", response_class=FileResponse)
    async def photo(photo_id: str) -> FileResponse:
        path = store.resolve(photo_id)
        if path is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        return FileResponse(path, media_type="image/jpeg", stat_result=path.stat())

    @application.get("/stream.mjpg", include_in_schema=False)
    async def stream() -> StreamingResponse:
        if video_service is None:
            raise HTTPException(status_code=404, detail="Live stream is not available")
        return StreamingResponse(
            video_service.mjpeg_frames(),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY.decode('ascii')}",
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/api/motion", response_model=MotionStatusResponse)
    async def motion_status() -> MotionStatusResponse:
        if video_service is None:
            raise HTTPException(status_code=404, detail="Motion detection is not available")
        return MotionStatusResponse(**video_service.status())

    @application.put(
        "/api/motion",
        response_model=MotionStatusResponse,
        responses={403: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    async def update_motion(
        request: Request, settings: MotionSettingsRequest
    ) -> MotionStatusResponse:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site motion updates are not allowed")
        if video_service is None:
            raise HTTPException(status_code=404, detail="Motion detection is not available")
        try:
            await video_service.set_motion_enabled(settings.enabled)
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail="Motion detection update failed") from exc
        return MotionStatusResponse(**video_service.status())

    @application.get("/api/videos", response_model=list[VideoResponse])
    async def videos() -> list[VideoResponse]:
        if video_store is None:
            return []
        return [VideoResponse(**asdict(video)) for video in video_store.list_videos()]

    @application.delete(
        "/api/videos/{video_id}",
        status_code=204,
        response_class=Response,
        responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def delete_video(video_id: str, request: Request) -> Response:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site deletion is not allowed")
        if video_store is None or not video_store.delete(video_id):
            raise HTTPException(status_code=404, detail="Video not found")
        return Response(status_code=204)

    @application.get("/videos/{video_id}", response_class=FileResponse)
    async def video(video_id: str) -> FileResponse:
        path = video_store.resolve(video_id) if video_store is not None else None
        if path is None:
            raise HTTPException(status_code=404, detail="Video not found")
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=f"{video_id}.mp4",
            stat_result=path.stat(),
        )

    return application


app = create_app()
