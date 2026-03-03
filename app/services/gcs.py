import logging
import os
import uuid

import requests
from werkzeug.datastructures import FileStorage


class GCSService:
    @staticmethod
    def _ensure_couchdrop_path_exists(token: str, folder_path: str) -> None:
        """Create Couchdrop folders on-demand to avoid partial/empty uploads."""
        if not folder_path or folder_path == "/":
            return

        headers = {"token": token.strip()}
        current = ""
        for segment in [part for part in folder_path.split("/") if part]:
            current = f"{current}/{segment}"
            check_response = requests.get(
                "https://api.couchdrop.io/manage/fileprops",
                headers=headers,
                params={"path": current},
                timeout=15,
            )
            if check_response.status_code == 200:
                continue

            mkdir_response = requests.post(
                "https://fileio.couchdrop.io/file/mkdir",
                headers=headers,
                params={"path": current},
                timeout=15,
            )
            if mkdir_response.status_code not in (200, 201):
                raise ValueError(f"Unable to create destination folder: {current}")

    @staticmethod
    def upload_file(file_obj: FileStorage, folder: str = "pod_events") -> str | None:
        """
        Uploads a Werkzeug FileStorage object to Couchdrop.
        Replaces direct GCS uploads to use the FSI POD integration.
        """
        if not file_obj:
            return None

        token = os.getenv("COUCHDROP_TOKEN")
        if not token:
            raise ValueError("CRITICAL: COUCHDROP_TOKEN is missing.")

        ext = file_obj.filename.split(".")[-1] if file_obj.filename and "." in file_obj.filename else "png"
        destination_path = f"/POD/{folder}/{uuid.uuid4().hex}.{ext}"

        file_obj.seek(0)
        file_bytes = file_obj.read()
        if not file_bytes:
            logging.error("Couchdrop Upload Aborted: empty file stream for %s", file_obj.filename)
            return None

        headers = {
            "token": token.strip(),
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(file_bytes)),
        }

        try:
            GCSService._ensure_couchdrop_path_exists(token, os.path.dirname(destination_path))

            response = requests.put(
                "https://fileio.couchdrop.io/file/upload",
                headers=headers,
                params={"path": destination_path},
                data=file_bytes,
                timeout=30,
            )

            if response.status_code not in (200, 201):
                logging.error("Couchdrop Upload Failed [%s]: %s", response.status_code, response.text)
                return None

            return destination_path

        except requests.RequestException as exc:
            logging.error("Couchdrop Connection Error: %s", str(exc))
            return None
