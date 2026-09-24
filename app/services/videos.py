from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

VIDEO_ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")


class VideoStorageFullError(OSError):
    """Raised when another recording cannot fit within the storage limits."""


@dataclass(frozen=True)
class Video:
    id: str
    captured_at: str
    url: str
    duration_seconds: int | None


class VideoStore:
    def __init__(
        self,
        directory: Path,
        maximum_videos: int,
        maximum_bytes: int = 500_000_000,
        minimum_free_bytes: int = 100_000_000,
    ) -> None:
        self.directory = directory
        self.maximum_videos = maximum_videos
        self.maximum_bytes = maximum_bytes
        self.minimum_free_bytes = minimum_free_bytes
        self.directory.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.directory / ".video-metadata.json"
        self._lock = RLock()

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
        with self._lock:
            durations = self._load_durations()
            paths = sorted(
                self.directory.glob("*.mp4"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            return [
                self._to_video(path, durations.get(path.stem))
                for path in paths
                if VIDEO_ID_PATTERN.fullmatch(path.stem)
            ]

    def set_duration(self, video_id: str, duration_seconds: float) -> None:
        with self._lock:
            path = self.path_for_new_video(video_id)
            if not path.is_file():
                return
            durations = self._load_durations()
            durations[video_id] = max(1, round(duration_seconds))
            self._save_durations(durations)

    def delete(self, video_id: str) -> bool:
        with self._lock:
            path = self.resolve(video_id)
            if path is None:
                return False

            path.unlink()
            durations = self._load_durations()
            if video_id in durations:
                del durations[video_id]
                self._save_durations(durations)
            return True

    def remove_excess(self) -> None:
        self._prune(enforce_free=True)

    def recover(self) -> None:
        """Run before opening the sole camera owner, never during a recording."""
        with self._lock:
            for path in self.directory.glob("*.part.mp4"):
                if (
                    VIDEO_ID_PATTERN.fullmatch(path.name.removesuffix(".part.mp4"))
                    and (path.is_file() or path.is_symlink())
                ):
                    path.unlink(missing_ok=True)
            self._prune()

    def prepare_recording(self, expected_bytes: int) -> None:
        """Reserve approximate space, retaining the newest completed videos."""
        with self._lock:
            if expected_bytes > self.maximum_bytes:
                raise VideoStorageFullError("Recording exceeds the video storage budget")
            free = shutil.disk_usage(self.directory).free
            reclaimable = sum(
                self.path_for_new_video(video.id).stat().st_size for video in self.list_videos()
            )
            if free + reclaimable < self.minimum_free_bytes + expected_bytes:
                raise VideoStorageFullError("Insufficient free space for recording")
            self._prune(reserve_bytes=expected_bytes, enforce_free=True)
            if shutil.disk_usage(self.directory).free < self.minimum_free_bytes + expected_bytes:
                raise VideoStorageFullError("Insufficient free space for recording")

    def has_recording_space(self, temporary_path: Path) -> bool:
        with self._lock:
            paths = [self.path_for_new_video(video.id) for video in self.list_videos()]
            if temporary_path.is_file():
                paths.append(temporary_path)
            return (
                sum(path.stat().st_size for path in paths) < self.maximum_bytes
                and shutil.disk_usage(self.directory).free > self.minimum_free_bytes
            )

    def _prune(self, reserve_bytes: int = 0, *, enforce_free: bool = False) -> None:
        with self._lock:
            durations = self._load_durations()
            changed = False
            videos = self.list_videos()
            total_bytes = sum(self.path_for_new_video(video.id).stat().st_size for video in videos)
            # Keep existing recordings until a new one is finalized; a failed start
            # must not evict the oldest file merely to reserve a count slot.
            count_limit = self.maximum_videos
            while videos and (
                len(videos) > count_limit
                or total_bytes + reserve_bytes > self.maximum_bytes
                or (
                    enforce_free
                    and shutil.disk_usage(self.directory).free
                    < self.minimum_free_bytes + reserve_bytes
                )
            ):
                video = videos.pop()
                path = self.path_for_new_video(video.id)
                total_bytes -= path.stat().st_size
                path.unlink(missing_ok=True)
                if video.id in durations:
                    del durations[video.id]
                    changed = True
            if changed:
                self._save_durations(durations)

    def _load_durations(self) -> dict[str, int]:
        try:
            metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        if not isinstance(metadata, dict):
            return {}
        return {
            video_id: duration
            for video_id, duration in metadata.items()
            if VIDEO_ID_PATTERN.fullmatch(video_id)
            and isinstance(duration, int)
            and duration > 0
        }

    def _save_durations(self, durations: dict[str, int]) -> None:
        temporary_path = self.metadata_path.with_name(
            f".{self.metadata_path.name}.{uuid4().hex}.tmp"
        )
        try:
            temporary_path.write_text(
                json.dumps(durations, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.metadata_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _to_video(path: Path, duration_seconds: int | None) -> Video:
        captured_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone()
        return Video(
            id=path.stem,
            captured_at=captured_at.isoformat(timespec="seconds"),
            url=f"/videos/{path.stem}",
            duration_seconds=duration_seconds,
        )
