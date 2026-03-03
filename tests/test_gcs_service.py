from io import BytesIO

from werkzeug.datastructures import FileStorage

from app.services.gcs import GCSService


def test_upload_file_rewinds_consumed_stream_and_saves_file(monkeypatch):
    created_dirs = []
    saved = {}

    def fake_makedirs(path, exist_ok=False):
        created_dirs.append((path, exist_ok))

    def fake_save(path):
        saved["path"] = path
        saved["bytes"] = file_obj.stream.read()

    monkeypatch.setattr("app.services.gcs.os.makedirs", fake_makedirs)

    file_obj = FileStorage(stream=BytesIO(b"photo-bytes"), filename="photo.jpg", content_type="image/jpeg")
    file_obj.stream.read()  # consume stream first; upload should still rewind before save
    file_obj.save = fake_save

    public_path = GCSService.upload_file(file_obj, folder="pod_photos/delivery")

    assert public_path is not None
    assert public_path.startswith("/POD/pod_photos/delivery/")
    assert public_path.endswith(".jpg")
    assert created_dirs and created_dirs[0][0] == "/POD/pod_photos/delivery"
    assert created_dirs[0][1] is True
    assert saved["bytes"] == b"photo-bytes"
    assert saved["path"].startswith("/POD/pod_photos/delivery/")


def test_upload_file_returns_none_for_empty_stream(monkeypatch):
    file_obj = FileStorage(stream=BytesIO(b""), filename="empty.jpg", content_type="image/jpeg")

    assert GCSService.upload_file(file_obj, folder="pod_photos/delivery") is None


def test_upload_file_rejects_path_traversal_folder():
    file_obj = FileStorage(stream=BytesIO(b"photo-bytes"), filename="photo.jpg", content_type="image/jpeg")

    assert GCSService.upload_file(file_obj, folder="../secrets") is None
