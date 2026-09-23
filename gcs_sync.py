import os
from pathlib import Path
from firebase_admin import storage

def is_cloud():
    return bool(os.environ.get("FIREBASE_CONFIG") or os.environ.get("FUNCTIONS_WORKER_RUNTIME"))

def pull_files(base_dir: Path):
    if not is_cloud():
        return
    bucket = storage.bucket('jobhunter-23070.firebasestorage.app')
    for blob in bucket.list_blobs():
        if blob.name.endswith((".json", ".jsonl", ".txt")):
            dest = base_dir / blob.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(dest))

def push_files(base_dir: Path):
    if not is_cloud():
        return
    bucket = storage.bucket('jobhunter-23070.firebasestorage.app')
    for path in base_dir.rglob("*"):
        if path.is_file() and path.suffix in [".json", ".jsonl", ".txt"]:
            blob_name = str(path.relative_to(base_dir)).replace("\\", "/")
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(path))
