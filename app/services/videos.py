from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

VIDEO_ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")


@dataclass(frozen=True)
class Video:
    id: str
    captured_at: str
    url: str


class VideoStore:
    def __init__(self, directory: Path, maximum_videos: int) -> None:
        self.directory = directory
        self.maximum_videos = maximum_videos
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for_new_video(self, video_id: str) -> Path:
        if not VIDEO_ID_PATTERN.fullmatch(video_id):
            raise ValueError("Invalid video ID")
        return self.directory / f"{video_id}.mp4"

    def path_for_recording(self, video_id: str) -> Path:
        path = self.path_for_new_video(video_id)
        return path.with_name(f"{video_id}.part.mp4")

    def resolve(self, video_id: str) -> Path | None:
        if not VIDEO_ID_PATTERN.fullmatch(video_id):
            return None
        candidate = self.path_for_new_video(video_id)
        return candidate if candidate.is_file() else None

    def list_videos(self) -> list[Video]:
        paths = sorted(
            self.directory.glob("*.mp4"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [self._to_video(path) for path in paths if VIDEO_ID_PATTERN.fullmatch(path.stem)]

    def remove_excess(self) -> None:
        for video in self.list_videos()[self.maximum_videos :]:
            path = self.resolve(video.id)
            if path is not None:
                path.unlink(missing_ok=True)

    @staticmethod
    def _to_video(path: Path) -> Video:
        captured_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone()
        return Video(
            id=path.stem,
            captured_at=captured_at.isoformat(timespec="seconds"),
            url=f"/videos/{path.stem}",
        )
