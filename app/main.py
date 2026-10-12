from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.config import Settings
from app.services.camera import (
    CameraBusyError,
    CameraCaptureError,
    CameraService,
    CameraTimeoutError,
)
from app.services.motion_settings import MotionTuning
from app.services.photos import PhotoStore
from app.services.picamera2 import MJPEG_BOUNDARY, Picamera2Service
from app.services.videos import VideoStorageFullError, VideoStore

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


class MotionTileResponse(BaseModel):
    x: int
    y: int
    changed_ratio: float
    confirmed: bool


class MotionAnalysisResponse(BaseModel):
    at: str
    width: int
    height: int
    tile_size: int
    reason: Literal["illumination", "settling", "still", "camera_motion", "candidate", "motion"]
    brightness_shift: int
    camera_shift_x: float
    camera_shift_y: float
    camera_shift_support: float
    raw_changed_ratio: float
    largest_tile_changed_ratio: float
    threshold: float
    min_changed_ratio: float
    consecutive_frames: int
    required_frames: int
    tiles: list[MotionTileResponse]


class MotionStatusResponse(BaseModel):
    enabled: bool
    state: Literal["disabled", "waiting", "recording", "cooldown", "error"]
    recording_source: Literal["motion", "manual"] | None
    stream_state: Literal["starting", "streaming", "stale"]
    last_frame_at: str | None
    error: str | None
    analysis: MotionAnalysisResponse | None = None
    last_recording_trigger: MotionAnalysisResponse | None = None
    rotation_degrees: Literal[0, 90, 180, 270]


class RotationRequest(BaseModel):
    degrees: Literal[0, 90, 180, 270]


class RotationResponse(BaseModel):
    degrees: Literal[0, 90, 180, 270]


class MotionSettingsRequest(BaseModel):
    enabled: bool


class MotionTuningRequest(BaseModel):
    minimum_record_seconds: int = Field(ge=1, le=3600)
    record_seconds: int = Field(ge=1, le=3600)
    maximum_record_seconds: int = Field(ge=1, le=3600)
    cooldown_seconds: int = Field(ge=1, le=3600)
    threshold: float = Field(gt=0, le=255)


class MotionTuningResponse(BaseModel):
    minimum_record_seconds: int
    record_seconds: int
    maximum_record_seconds: int
    cooldown_seconds: int
    threshold: float


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
    # Different URLs prevent a cached script from running against a new template.
    # Compute once per process, not on every request to the Raspberry Pi.
    asset_versions = {
        name: sha256((APP_DIR / "static" / name).read_bytes()).hexdigest()[:16]
        for name in ("css/style.css", "js/app.js")
    }

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
            context={
                "live_stream_available": video_service is not None,
                "asset_versions": asset_versions,
            },
            headers={"Cache-Control": "no-cache"},
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
    async def motion_status(response: Response) -> MotionStatusResponse:
        if video_service is None:
            raise HTTPException(status_code=404, detail="Motion detection is not available")
        response.headers["Cache-Control"] = "no-store"
        return MotionStatusResponse(**video_service.status())

    @application.put(
        "/api/motion",
        response_model=MotionStatusResponse,
        responses={403: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    async def update_motion(
        request: Request, response: Response, settings: MotionSettingsRequest
    ) -> MotionStatusResponse:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site motion updates are not allowed")
        if video_service is None:
            raise HTTPException(status_code=404, detail="Motion detection is not available")
        try:
            await video_service.set_motion_enabled(settings.enabled)
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail="Motion detection update failed") from exc
        response.headers["Cache-Control"] = "no-store"
        return MotionStatusResponse(**video_service.status())

    @application.get("/api/motion/settings", response_model=MotionTuningResponse)
    async def motion_settings(response: Response) -> MotionTuningResponse:
        if video_service is None:
            raise HTTPException(status_code=404, detail="Motion settings are not available")
        response.headers["Cache-Control"] = "no-store"
        return MotionTuningResponse(**video_service.motion_tuning.as_dict())

    @application.put(
        "/api/motion/settings",
        response_model=MotionTuningResponse,
        responses={
            403: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def update_motion_settings(
        request: Request, response: Response, tuning: MotionTuningRequest
    ) -> MotionTuningResponse:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(
                status_code=403, detail="Cross-site settings updates are not allowed"
            )
        if video_service is None:
            raise HTTPException(status_code=404, detail="Motion settings are not available")
        new_tuning = MotionTuning(**tuning.model_dump())
        try:
            new_tuning.validate()
            saved_tuning = await video_service.set_motion_tuning(new_tuning)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409, detail="Settings cannot be changed during a recording"
            ) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Settings could not be saved") from exc
        response.headers["Cache-Control"] = "no-store"
        return MotionTuningResponse(**saved_tuning.as_dict())

    @application.post(
        "/api/recording/start",
        response_model=MotionStatusResponse,
        responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
                   409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    async def start_manual_recording(request: Request, response: Response) -> MotionStatusResponse:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site recording is not allowed")
        if video_service is None:
            raise HTTPException(status_code=404, detail="Video recording is not available")
        try:
            await video_service.start_manual_recording()
        except RuntimeError as exc:
            if str(exc) == "A recording is already active":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=503, detail="Camera is not available") from exc
        except VideoStorageFullError as exc:
            raise HTTPException(status_code=503, detail="Video storage is full") from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Video recording could not be started"
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return MotionStatusResponse(**video_service.status())

    @application.post(
        "/api/recording/stop",
        response_model=MotionStatusResponse,
        responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
                   409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    async def stop_manual_recording(request: Request, response: Response) -> MotionStatusResponse:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site recording is not allowed")
        if video_service is None:
            raise HTTPException(status_code=404, detail="Video recording is not available")
        try:
            await video_service.stop_manual_recording()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail="No manual recording is active") from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Video recording could not be stopped"
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return MotionStatusResponse(**video_service.status())

    @application.put(
        "/api/rotation",
        response_model=RotationResponse,
        responses={403: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
                   503: {"model": ErrorResponse}},
    )
    async def update_rotation(request: Request, rotation: RotationRequest) -> RotationResponse:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site rotation is not allowed")
        if video_service is None:
            raise HTTPException(status_code=404, detail="Rotation is not available")
        try:
            degrees = await video_service.set_rotation(rotation.degrees)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409, detail="Rotation is unavailable while recording"
            ) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Rotation could not be saved") from exc
        return RotationResponse(degrees=degrees)

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
