from io import BytesIO

from werkzeug.datastructures import FileStorage

from app.services.gcs import GCSService


class _Response:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def test_upload_file_rewinds_consumed_stream_and_uploads_bytes(monkeypatch):
    monkeypatch.setenv("COUCHDROP_TOKEN", "test-token")

    calls = {"upload_data": None, "paths": []}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["paths"].append(("get", params["path"]))
        return _Response(status_code=200)

    def fake_post(url, headers=None, params=None, data=None, timeout=None):
        if url.endswith("/file/mkdir"):
            calls["paths"].append(("mkdir", params["path"]))
            return _Response(status_code=201)
        calls["upload_data"] = data
        return _Response(status_code=201)

    monkeypatch.setattr("app.services.gcs.requests.get", fake_get)
    monkeypatch.setattr("app.services.gcs.requests.post", fake_post)

    file_obj = FileStorage(stream=BytesIO(b"photo-bytes"), filename="photo.jpg", content_type="image/jpeg")
    file_obj.stream.read()  # consume stream first; upload should still rewind and send bytes

    path = GCSService.upload_file(file_obj, folder="pod_photos/delivery")

    assert path is not None
    assert calls["upload_data"] == b"photo-bytes"


def test_upload_file_returns_none_for_empty_stream(monkeypatch):
    monkeypatch.setenv("COUCHDROP_TOKEN", "test-token")

    def fake_get(*_args, **_kwargs):
        return _Response(status_code=200)

    def fake_post(*_args, **_kwargs):
        return _Response(status_code=201)

    monkeypatch.setattr("app.services.gcs.requests.get", fake_get)
    monkeypatch.setattr("app.services.gcs.requests.post", fake_post)

    file_obj = FileStorage(stream=BytesIO(b""), filename="empty.jpg", content_type="image/jpeg")

    assert GCSService.upload_file(file_obj, folder="pod_photos/delivery") is None
