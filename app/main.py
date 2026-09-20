from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
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

APP_DIR = Path(__file__).resolve().parent


class PhotoResponse(BaseModel):
    id: str
    captured_at: str
    url: str


class ErrorResponse(BaseModel):
    detail: str


def create_app(
    settings: Settings | None = None,
    camera_service: CameraService | None = None,
) -> FastAPI:
    active_settings = settings or Settings.from_environment()
    store = PhotoStore(active_settings.photo_dir, active_settings.maximum_photos)
    camera = camera_service or CameraService(active_settings, store)
    templates = Jinja2Templates(directory=APP_DIR / "templates")

    application = FastAPI(title="raspi-camera-web", version="0.1.0")
    application.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    application.state.photo_store = store
    application.state.camera_service = camera

    @application.get("/", include_in_schema=False)
    async def index(request: Request):
        return templates.TemplateResponse(request=request, name="index.html")

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

    return application


app = create_app()
