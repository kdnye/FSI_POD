import os
import requests
import logging
import hashlib
from datetime import datetime

from flask import current_app, has_app_context
from werkzeug.utils import secure_filename

class CouchdropService:
    @staticmethod
    def _get_storage_module():
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("google-cloud-storage is required for queued Couchdrop uploads.") from exc
        return storage

    @staticmethod
    def _get_bucket_name() -> str:
        if has_app_context():
            configured = (current_app.config.get("GCS_BUCKET_NAME") or "").strip()
            if configured:
                return configured
        return (os.getenv("GCS_BUCKET_NAME") or "").strip()

    @staticmethod
    def _ensure_path_exists(token, folder_path, timeout_seconds=15):
        headers = {"token": token}
        normalized_path = (folder_path or "").strip("/")
        if not normalized_path:
            return True

        cumulative_path = ""
        for segment in normalized_path.split("/"):
            cumulative_path = f"{cumulative_path}/{segment}"

            check_response = requests.get(
                "https://api.couchdrop.io/manage/fileprops",
                headers=headers,
                params={"path": cumulative_path},
                timeout=timeout_seconds,
            )
            if check_response.status_code == 200:
                continue

            mkdir_response = requests.post(
                "https://fileio.couchdrop.io/file/mkdir",
                headers=headers,
                params={"path": cumulative_path},
                timeout=timeout_seconds,
            )
            if mkdir_response.status_code not in (200, 201):
                logging.error(
                    "Couchdrop mkdir failed for %s [check=%s, mkdir=%s]: %s",
                    cumulative_path,
                    check_response.status_code,
                    mkdir_response.status_code,
                    mkdir_response.text,
                )
                return False

        return True

    @staticmethod
    def upload_driver_paperwork(user, file_storage):
        timeout_seconds = 15
        raw_token = os.getenv("COUCHDROP_TOKEN")
        if not raw_token:
            raise ValueError("CRITICAL: COUCHDROP_TOKEN environment variable is missing or empty.")
            
        token = raw_token.strip()
        
        # 1. Format names safely with underscores to prevent folder name truncation
        driver_name = f"{user.first_name}_{user.last_name}".replace(" ", "_")
        date_str = datetime.now().strftime("%Y-%m-%d")
        
        folder_path = f"/Paperwork/{driver_name}/{date_str}"
        remote_path = f"{folder_path}/{file_storage.filename}"
        
        if not CouchdropService._ensure_path_exists(token, folder_path, timeout_seconds):
            logging.error("Couchdrop upload aborted: unable to ensure folder path %s", folder_path)
            return False

        file_storage.stream.seek(0)
        file_bytes = file_storage.read()
        if not file_bytes:
            logging.error("Couchdrop upload aborted: received empty file bytes.")
            return False

        headers = {
            "token": token,
        }

        files = {
            "file": (
                file_storage.filename,
                file_bytes,
                file_storage.content_type or "application/octet-stream",
            )
        }
        
        try:
            response = requests.post(
                "https://fileio.couchdrop.io/file/upload",
                headers=headers,
                params={"path": remote_path},
                files=files,
                timeout=timeout_seconds,
            )
            
            if response.status_code not in (200, 201):
                logging.error(f"Couchdrop Upload Failed [{response.status_code}]: {response.text}")
                return False
                
            return True
            
        except requests.RequestException as e:
            logging.error(f"Couchdrop Connection Error: {str(e)}")
            return False

    @staticmethod
    def stage_driver_paperwork_for_task(user, file_storage):
        if not file_storage or not getattr(file_storage, "filename", ""):
            logging.error("Couchdrop task staging aborted: missing filename.")
            return None

        file_storage.stream.seek(0)
        file_bytes = file_storage.read()
        if not file_bytes:
            logging.error("Couchdrop task staging aborted: empty file bytes.")
            return None

        bucket_name = CouchdropService._get_bucket_name()
        if not bucket_name:
            raise RuntimeError("GCS_BUCKET_NAME is required for queued Couchdrop uploads.")

        safe_name = secure_filename(file_storage.filename)
        driver_name = f"{user.first_name}_{user.last_name}".replace(" ", "_")
        date_str = datetime.now().strftime("%Y-%m-%d")
        folder_path = f"/Paperwork/{driver_name}/{date_str}"
        remote_path = f"{folder_path}/{safe_name}"

        content_hash = hashlib.sha256(file_bytes).hexdigest()
        idempotency_key = hashlib.sha256(
            f"{getattr(user, 'id', 'unknown')}|{remote_path}|{content_hash}".encode("utf-8")
        ).hexdigest()
        staged_blob_name = f"couchdrop_queue/{date_str}/{idempotency_key}/{safe_name}"

        storage = CouchdropService._get_storage_module()
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(staged_blob_name)
        blob.upload_from_string(file_bytes, content_type=file_storage.content_type or "application/octet-stream")

        return {
            "actor_user_id": getattr(user, "id", None),
            "original_filename": safe_name,
            "content_type": file_storage.content_type or "application/octet-stream",
            "staged_blob_name": staged_blob_name,
            "remote_path": remote_path,
            "idempotency_key": idempotency_key,
        }

    @staticmethod
    def upload_staged_paperwork(staged_blob_name, remote_path, filename, content_type):
        timeout_seconds = 15
        raw_token = os.getenv("COUCHDROP_TOKEN")
        if not raw_token:
            raise ValueError("CRITICAL: COUCHDROP_TOKEN environment variable is missing or empty.")

        bucket_name = CouchdropService._get_bucket_name()
        if not bucket_name:
            raise RuntimeError("GCS_BUCKET_NAME is required for queued Couchdrop uploads.")

        storage = CouchdropService._get_storage_module()
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob((staged_blob_name or "").strip())

        if not blob.exists():
            logging.error("Couchdrop task upload failed: staged blob not found %s", staged_blob_name)
            return False, "staged_blob_missing"

        file_bytes = blob.download_as_bytes()
        if not file_bytes:
            logging.error("Couchdrop task upload failed: staged blob empty %s", staged_blob_name)
            return False, "staged_blob_empty"

        token = raw_token.strip()
        folder_path = "/" + "/".join((remote_path or "").strip("/").split("/")[:-1])
        if not CouchdropService._ensure_path_exists(token, folder_path, timeout_seconds):
            return False, "folder_create_failed"

        headers = {"token": token}
        files = {
            "file": (
                filename,
                file_bytes,
                content_type or "application/octet-stream",
            )
        }

        try:
            response = requests.post(
                "https://fileio.couchdrop.io/file/upload",
                headers=headers,
                params={"path": remote_path},
                files=files,
                timeout=timeout_seconds,
            )
            if response.status_code not in (200, 201):
                logging.error("Couchdrop task upload failed [%s]: %s", response.status_code, response.text)
                return False, "upload_http_error"
            return True, "uploaded"
        except requests.RequestException as exc:
            logging.error("Couchdrop task connection error: %s", str(exc))
            return False, "upload_connection_error"
