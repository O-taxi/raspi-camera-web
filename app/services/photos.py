from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PHOTO_ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")


@dataclass(frozen=True)
class Photo:
    id: str
    captured_at: str
    url: str


class PhotoStore:
    def __init__(self, directory: Path, maximum_photos: int) -> None:
        self.directory = directory
        self.maximum_photos = maximum_photos
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for_new_photo(self, photo_id: str) -> Path:
        if not PHOTO_ID_PATTERN.fullmatch(photo_id):
            raise ValueError("Invalid photo ID")
        return self.directory / f"{photo_id}.jpg"

    def resolve(self, photo_id: str) -> Path | None:
        if not PHOTO_ID_PATTERN.fullmatch(photo_id):
            return None

        candidate = self.directory / f"{photo_id}.jpg"
        if not candidate.is_file():
            return None
        return candidate

    def list_photos(self) -> list[Photo]:
        paths = sorted(
            self.directory.glob("*.jpg"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [self._to_photo(path) for path in paths if PHOTO_ID_PATTERN.fullmatch(path.stem)]

    def delete(self, photo_id: str) -> bool:
        path = self.resolve(photo_id)
        if path is None:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def remove_excess(self) -> None:
        paths = sorted(
            self.directory.glob("*.jpg"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in paths[self.maximum_photos :]:
            path.unlink(missing_ok=True)

    @staticmethod
    def _to_photo(path: Path) -> Photo:
        captured_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone()
        return Photo(
            id=path.stem,
            captured_at=captured_at.isoformat(timespec="seconds"),
            url=f"/photos/{path.stem}",
        )
