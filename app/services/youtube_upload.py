import os
import logging
from typing import Optional, Dict, Any
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from app.services.google_auth import get_credentials

logger = logging.getLogger(__name__)


def upload_short(file_path: str, metadata: Optional[Dict[str, Any]] = None) -> dict:
    """
    Upload a video to YouTube as a Short.
    
    Args:
        file_path: Path to the video file (must be vertical 9:16, ≤60s for Shorts)
        metadata: Dict with keys like title, Deskripsi, Tag, Thumbnail, etc.
    
    Returns:
        dict with video_id and upload_url
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Video file not found: {file_path}")

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    meta = metadata or {}
    title = meta.get("title", "YouTube Short")
    description = meta.get("Deskripsi", meta.get("description", ""))
    tags = meta.get("Tag", meta.get("tags", ""))
    privacy = meta.get("privacy", "unlisted")

    # Ensure #Shorts tag is in description for YouTube to detect it as a Short
    if "#Shorts" not in description:
        description = f"{description}\n#Shorts".strip()

    # Parse tags: support comma-separated string or list
    if isinstance(tags, str):
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        tag_list = tags
    else:
        tag_list = []

    # Always include "Shorts" tag
    if "Shorts" not in tag_list:
        tag_list.append("Shorts")

    body = {
        "snippet": {
            "title": title[:100],  # YouTube max title is 100 chars
            "description": description[:5000],
            "tags": tag_list,
            "categoryId": "22",  # People & Blogs (default)
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    logger.info(f"Uploading '{title}' to YouTube...")

    media = MediaFileUpload(
        file_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    # Execute resumable upload with progress logging
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            logger.info(f"Upload progress: {progress}%")

    video_id = response["id"]
    upload_url = f"https://youtube.com/shorts/{video_id}"

    logger.info(f"Upload complete! URL: {upload_url}")

    # Set thumbnail if provided
    thumbnail_path = meta.get("Thumbnail", "")
    if thumbnail_path:
        if os.path.exists(thumbnail_path):
            try:
                logger.info(f"Setting custom thumbnail from {thumbnail_path}...")
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path, mimetype='image/jpeg'),
                ).execute()
                logger.info("Custom thumbnail set successfully.")
            except Exception as e:
                logger.warning(f"Failed to set thumbnail: {e}")
        else:
            logger.warning(f"Thumbnail path provided but file not found: {thumbnail_path}")
    else:
        logger.info("No thumbnail provided in metadata.")

    return {
        "video_id": video_id,
        "upload_url": upload_url,
    }
