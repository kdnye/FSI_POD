import os
import uuid
from google.cloud import storage
from werkzeug.datastructures import FileStorage

class GCSService:
    @staticmethod
    def upload_file(file_obj: FileStorage, folder: str = "pod_events") -> str | None:
        """
        Uploads a Werkzeug FileStorage object to GCS.
        Relies on Cloud Run default service account for IAM auth.
        """
        if not file_obj:
            return None

        bucket_name = os.getenv("GCS_BUCKET_NAME")
        if not bucket_name:
            raise ValueError("CRITICAL: GCS_BUCKET_NAME environment variable is missing.")

        # Initialize client (auto-discovers Cloud Run service account credentials)
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        # Generate unique path: folder/uuid.ext
        ext = file_obj.filename.split('.')[-1] if '.' in file_obj.filename else 'bin'
        destination_blob_name = f"{folder}/{uuid.uuid4().hex}.{ext}"
        
        blob = bucket.blob(destination_blob_name)

        # Ensure stream is at position 0 before uploading
        file_obj.seek(0)
        blob.upload_from_file(file_obj.stream, content_type=file_obj.content_type)

        # Return standard gs:// URI for database storage
        return f"gs://{bucket_name}/{destination_blob_name}"
