import os
from types import SimpleNamespace

import pytest

from app.services.videos import VideoStorageFullError, VideoStore


def test_video_store_persists_duration_and_cleans_metadata(tmp_path) -> None:
    store = VideoStore(tmp_path / "videos", maximum_videos=1)
    older_id = "20260920-120000-00000001"
    newer_id = "20260920-120001-00000002"
    older_path = store.path_for_new_video(older_id)
    older_path.write_bytes(b"mp4")
    os.utime(older_path, (1, 1))
    store.set_duration(older_id, 12.4)
    newer_path = store.path_for_new_video(newer_id)
    newer_path.write_bytes(b"mp4")
    os.utime(newer_path, (2, 2))
    store.set_duration(newer_id, 7.2)

    videos = store.list_videos()

    assert videos[0].id == newer_id
    assert videos[0].duration_seconds == 7
    store.remove_excess()
    assert store.resolve(older_id) is None
    assert older_id not in store._load_durations()


def test_video_store_deletion_removes_duration_metadata(tmp_path) -> None:
    store = VideoStore(tmp_path / "videos", maximum_videos=3)
    video_id = "20260920-120000-00000001"
    store.path_for_new_video(video_id).write_bytes(b"mp4")
    store.set_duration(video_id, 12.4)

    assert store.delete(video_id)
    assert store.resolve(video_id) is None
    assert video_id not in store._load_durations()


def test_recovery_removes_only_managed_partial_files(tmp_path) -> None:
    store = VideoStore(tmp_path, 3)
    partial = store.path_for_recording("20260920-120000-00000001")
    partial.write_bytes(b"unfinished")
    unrelated = tmp_path / "keep.part.mp4"
    unrelated.write_bytes(b"unrelated")
    completed = store.path_for_new_video("20260920-120001-00000002")
    completed.write_bytes(b"mp4")

    store.recover()

    assert not partial.exists()
    assert unrelated.exists()
    assert completed.exists()


def test_video_byte_limit_deletes_oldest_and_preserves_metadata(tmp_path) -> None:
    store = VideoStore(tmp_path, 3, maximum_bytes=5)
    older = "20260920-120000-00000001"
    newer = "20260920-120001-00000002"
    for index, video_id in enumerate((older, newer), start=1):
        path = store.path_for_new_video(video_id)
        path.write_bytes(b"mp4")
        os.utime(path, (index, index))
        store.set_duration(video_id, 3)

    store.remove_excess()

    assert store.resolve(older) is None
    assert store.resolve(newer) is not None
    assert store._load_durations() == {newer: 3}


def test_recording_reserves_space_and_rejects_full_filesystem(tmp_path, monkeypatch) -> None:
    store = VideoStore(tmp_path, 3, maximum_bytes=100, minimum_free_bytes=10)
    monkeypatch.setattr("app.services.videos.shutil.disk_usage", lambda _: SimpleNamespace(free=15))
    with pytest.raises(VideoStorageFullError):
        store.prepare_recording(expected_bytes=20)


def test_impossible_reservation_preserves_existing_recordings(tmp_path, monkeypatch) -> None:
    store = VideoStore(tmp_path, 3, maximum_bytes=100, minimum_free_bytes=10)
    existing = store.path_for_new_video("20260920-120000-00000001")
    existing.write_bytes(b"mp4")
    monkeypatch.setattr("app.services.videos.shutil.disk_usage", lambda _: SimpleNamespace(free=15))
    with pytest.raises(VideoStorageFullError):
        store.prepare_recording(expected_bytes=20)
    assert existing.exists()


def test_count_reservation_preserves_old_video_until_new_one_is_saved(tmp_path) -> None:
    store = VideoStore(tmp_path, 1, maximum_bytes=100)
    older = store.path_for_new_video("20260920-120000-00000001")
    older.write_bytes(b"mp4")
    store.prepare_recording(expected_bytes=20)
    assert older.exists()

    newer = store.path_for_new_video("20260920-120001-00000002")
    newer.write_bytes(b"mp4")
    os.utime(newer, (older.stat().st_mtime + 1, older.stat().st_mtime + 1))
    store.remove_excess()
    assert not older.exists()
    assert newer.exists()


def test_oversized_recording_does_not_delete_existing_videos(tmp_path) -> None:
    store = VideoStore(tmp_path, 3, maximum_bytes=10)
    existing = store.path_for_new_video("20260920-120000-00000001")
    existing.write_bytes(b"mp4")
    with pytest.raises(VideoStorageFullError):
        store.prepare_recording(expected_bytes=11)
    assert existing.exists()


def test_recording_space_counts_in_progress_video(tmp_path) -> None:
    store = VideoStore(tmp_path, 3, maximum_bytes=10)
    existing = store.path_for_new_video("20260920-120000-00000001")
    existing.write_bytes(b"mp4")
    partial = store.path_for_recording("20260920-120001-00000002")
    partial.write_bytes(b"12345678")
    assert not store.has_recording_space(partial)
