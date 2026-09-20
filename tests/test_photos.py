import os

from app.services.photos import PhotoStore


def test_resolve_rejects_invalid_photo_id(settings) -> None:
    store = PhotoStore(settings.photo_dir, settings.maximum_photos)

    assert store.resolve("../../etc/passwd") is None
    assert store.resolve("not-a-photo") is None


def test_remove_excess_keeps_newest_photos(settings) -> None:
    store = PhotoStore(settings.photo_dir, maximum_photos=2)
    paths = [
        store.path_for_new_photo("20260920-120000-00000001"),
        store.path_for_new_photo("20260920-120001-00000002"),
        store.path_for_new_photo("20260920-120002-00000003"),
    ]
    for index, path in enumerate(paths):
        path.write_bytes(b"jpeg")
        os.utime(path, (index, index))

    store.remove_excess()

    assert not paths[0].exists()
    assert paths[1].exists()
    assert paths[2].exists()


def test_delete_removes_only_managed_photo(settings) -> None:
    store = PhotoStore(settings.photo_dir, settings.maximum_photos)
    photo = store.path_for_new_photo("20260920-120000-00000001")
    photo.write_bytes(b"jpeg")

    assert store.delete("20260920-120000-00000001") is True
    assert not photo.exists()
    assert store.delete("../../etc/passwd") is False
    assert store.delete("20260920-120000-00000001") is False
