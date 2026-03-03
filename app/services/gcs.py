import logging
import os
import uuid

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
