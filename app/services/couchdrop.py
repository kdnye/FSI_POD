import os
import requests
import logging
from datetime import datetime

class CouchdropService:
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
        
        headers = {
            "token": token,
            "Content-Type": "application/octet-stream"
        }

        if not CouchdropService._ensure_path_exists(token, folder_path, timeout_seconds):
            logging.error("Couchdrop upload aborted: unable to ensure folder path %s", folder_path)
            return False
        
        # Rewind the stream before reading so uploads are not empty on retries.
        stream = getattr(file_storage, "stream", None)
        if stream and callable(getattr(stream, "seek", None)):
            stream.seek(0)
        elif callable(getattr(file_storage, "seek", None)):
            file_storage.seek(0)

        # Read file into memory once so it can be retried without re-seeking
        file_bytes = file_storage.read()
        if not file_bytes:
            logging.error("Couchdrop upload aborted: received empty file bytes.")
            return False
        
        try:
            response = requests.post(
                "https://fileio.couchdrop.io/file/upload",
                headers=headers,
                params={"path": remote_path},
                data=file_bytes,
                timeout=timeout_seconds,
            )
            
            if response.status_code not in (200, 201):
                logging.error(f"Couchdrop Upload Failed [{response.status_code}]: {response.text}")
                return False
                
            return True
            
        except Exception as e:
            logging.error(f"Couchdrop Connection Error: {str(e)}")
            return False
