from io import BytesIO

from app import db
from models import Role, User


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id


def test_paperwork_upload_enqueues_couchdrop_jobs(client, app, monkeypatch):
    with app.app_context():
        user = User(
            email="driver-upload@example.com",
            password_hash="hash",
            role=Role.EMPLOYEE,
            employee_approved=True,
            first_name="Driver",
            last_name="One",
        )
        db.session.add(user)
        db.session.commit()
        _login(client, user.id)

    staged_calls = []
    queued = []

    def _fake_stage(current_user, file_storage):
        staged_calls.append((current_user.id, file_storage.filename))
        return {
            "actor_user_id": current_user.id,
            "original_filename": file_storage.filename,
            "content_type": "application/pdf",
            "staged_blob_name": f"couchdrop_queue/test/{file_storage.filename}",
            "remote_path": f"/Paperwork/Driver_One/2026-01-01/{file_storage.filename}",
            "idempotency_key": f"idem-{file_storage.filename}",
        }

    monkeypatch.setattr("app.blueprints.paperwork.routes.CouchdropService.stage_driver_paperwork_for_task", _fake_stage)
    monkeypatch.setattr("app.blueprints.paperwork.routes.enqueue_couchdrop_task", lambda payload: queued.append(payload))

    response = client.post(
        "/upload",
        data={
            "scans": [
                (BytesIO(b"doc-1"), "scan-1.pdf"),
                (BytesIO(b"doc-2"), "scan-2.pdf"),
            ]
        },
        headers={"Accept": "application/json"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["success_count"] == 2
    assert len(staged_calls) == 2
    assert len(queued) == 2


def test_paperwork_upload_is_non_blocking_when_individual_stage_fails(client, app, monkeypatch):
    with app.app_context():
        user = User(
            email="driver-upload2@example.com",
            password_hash="hash",
            role=Role.EMPLOYEE,
            employee_approved=True,
            first_name="Driver",
            last_name="Two",
        )
        db.session.add(user)
        db.session.commit()
        _login(client, user.id)

    staged = iter(
        [
            None,
            {
                "actor_user_id": user.id,
                "original_filename": "scan-2.pdf",
                "content_type": "application/pdf",
                "staged_blob_name": "couchdrop_queue/test/scan-2.pdf",
                "remote_path": "/Paperwork/Driver_Two/2026-01-01/scan-2.pdf",
                "idempotency_key": "idem-2",
            },
        ]
    )

    monkeypatch.setattr("app.blueprints.paperwork.routes.CouchdropService.stage_driver_paperwork_for_task", lambda *_args: next(staged))
    monkeypatch.setattr("app.blueprints.paperwork.routes.enqueue_couchdrop_task", lambda _payload: None)

    response = client.post(
        "/upload",
        data={
            "scans": [
                (BytesIO(b"bad"), "scan-1.pdf"),
                (BytesIO(b"ok"), "scan-2.pdf"),
            ]
        },
        headers={"Accept": "application/json"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["success_count"] == 1
