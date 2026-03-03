import os
import requests
import logging
from datetime import datetime

class CouchdropService:
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
            # 2. Optimistic Upload: Try to upload directly.
            # If the folder already exists (e.g. from File #1 in the batch), Files 2, 3, and 4 succeed instantly.
            response = requests.post(
                "https://fileio.couchdrop.io/file/upload",
                headers=headers,
                params={"path": remote_path},
                data=file_bytes,
                timeout=timeout_seconds,
            )
            
            # 3. If it fails because the folders don't exist, we precisely build them
            if response.status_code == 404 and "parent-folder-not-found" in response.text:
                logging.info(f"Folders missing. Building path for: {folder_path}")
                
                driver_dir = f"/Paperwork/{driver_name}"
                
                # Check if the Driver's folder exists using Couchdrop's management API
                check_driver = requests.get(
                    "https://api.couchdrop.io/manage/fileprops", 
                    headers={"token": token}, 
                    params={"path": driver_dir},
                    timeout=timeout_seconds,
                )
                if check_driver.status_code != 200:
                    requests.post(
                        "https://fileio.couchdrop.io/file/mkdir", 
                        headers={"token": token}, 
                        params={"path": driver_dir},
                        timeout=timeout_seconds,
                    )
                    
                # Check if the Date folder exists
                check_date = requests.get(
                    "https://api.couchdrop.io/manage/fileprops", 
                    headers={"token": token}, 
                    params={"path": folder_path},
                    timeout=timeout_seconds,
                )
                if check_date.status_code != 200:
                    requests.post(
                        "https://fileio.couchdrop.io/file/mkdir", 
                        headers={"token": token}, 
                        params={"path": folder_path},
                        timeout=timeout_seconds,
                    )
                    
                # 4. Retry the exact same upload now that the path is guaranteed to exist
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
