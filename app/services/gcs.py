import logging
import os
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from flask import current_app, has_app_context
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


class GCSService:
    @staticmethod
    def upload_file(file_obj: FileStorage, folder: str = "pod_events") -> str | None:
        """Save a Werkzeug FileStorage object under /POD for POD page access."""
        if not file_obj:
            return None

        if not getattr(file_obj, "filename", ""):
            logging.error("POD upload aborted: missing filename.")
            return None

        safe_folder = os.path.normpath(folder or "pod_events").strip("/")
        if safe_folder in ("", "."):
            safe_folder = "pod_events"

        if safe_folder.startswith("..") or "/../" in f"/{safe_folder}/":
            logging.error("POD upload aborted: invalid folder path '%s'.", folder)
            return None

        safe_name = secure_filename(file_obj.filename)
        ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else "png"

        generated_name = f"{uuid.uuid4().hex}.{ext}"
        destination_path = os.path.join("/POD", safe_folder, generated_name)
        public_path = f"/POD/{safe_folder}/{generated_name}"

        try:
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)

            file_obj.stream.seek(0)
            if not file_obj.stream.read(1):
                logging.error("POD upload aborted: empty file stream for %s", file_obj.filename)
                return None

            file_obj.stream.seek(0)
            file_obj.save(destination_path)
            return public_path
        except Exception as exc:
            logging.error("POD upload failed for %s: %s", file_obj.filename, str(exc))
            return None




def build_media_access_url(blob_name: str | None, public_base_url: str | None = None) -> str | None:
    cleaned_blob_name = str(blob_name or "").strip()
    if not cleaned_blob_name:
        return None

    if cleaned_blob_name.startswith(("http://", "https://")):
        return cleaned_blob_name

    signed_url = generate_signed_url(cleaned_blob_name)
    if signed_url:
        return signed_url

    if cleaned_blob_name.startswith("gs://"):
        return None

    base_url = str(public_base_url or "").strip().rstrip("/")
    if not base_url:
        if has_app_context():
            base_url = str(current_app.config.get("PUBLIC_SERVICE_URL", "")).strip().rstrip("/")
        if not base_url:
            base_url = str(os.getenv("PUBLIC_SERVICE_URL", "")).strip().rstrip("/")

    if not base_url:
        return None

    normalized_path = cleaned_blob_name if cleaned_blob_name.startswith("/") else f"/{cleaned_blob_name}"
    return f"{base_url}{normalized_path}"

def _get_storage_module():
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage is required to generate signed URLs.") from exc
    return storage


def generate_signed_url(blob_name: str, expiration_days: int = 7) -> str | None:
    cleaned_blob_name = str(blob_name or "").strip()
    if not cleaned_blob_name:
        return None

    bucket_name = ""
    if has_app_context():
        bucket_name = current_app.config.get("GCS_BUCKET_NAME", "").strip()
    if not bucket_name:
        bucket_name = os.getenv("GCS_BUCKET_NAME", "").strip()

    if cleaned_blob_name.startswith("gs://"):
        parsed = urlparse(cleaned_blob_name)
        if not parsed.netloc or not parsed.path:
            return None
        blob_bucket_name = parsed.netloc.strip()
        cleaned_blob_name = parsed.path.lstrip("/")
        if blob_bucket_name:
            bucket_name = blob_bucket_name

    cleaned_blob_name = cleaned_blob_name.lstrip("/")
    if cleaned_blob_name.startswith("POD/"):
        cleaned_blob_name = cleaned_blob_name[4:]
    if cleaned_blob_name in {"", "."} or ".." in cleaned_blob_name.split("/"):
        return None

    if not bucket_name:
        logging.warning("Signed URL generation skipped: GCS_BUCKET_NAME is not configured.")
        return None

    try:
        storage = _get_storage_module()
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(cleaned_blob_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=expiration_days),
            method="GET",
        )
    except Exception as exc:
        logging.error("Failed to generate signed URL for blob '%s': %s", cleaned_blob_name, exc)
        return None
