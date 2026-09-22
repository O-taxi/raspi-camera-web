import os

from app.services.videos import VideoStore


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
