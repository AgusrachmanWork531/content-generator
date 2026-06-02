import os
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Allow insecure transport for local development (consistent with other implementation)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

logger = logging.getLogger(__name__)


@dataclass
class TokenData:
    token: str
    refresh_token: Optional[str]
    token_uri: str
    client_id: str
    client_secret: str
    scopes: List[str]


def load_token_data(token_json_path: str) -> TokenData:
    with open(token_json_path, "r", encoding="utf-8") as f:
        d = json.load(f)

    return TokenData(
        token=d["token"],
        refresh_token=d.get("refresh_token"),
        token_uri=d["token_uri"],
        client_id=d["client_id"],
        client_secret=d["client_secret"],
        scopes=d.get("scopes") or [],
    )


def build_credentials(token_json_path: str, refresh_if_needed: bool = True) -> Credentials:
    td = load_token_data(token_json_path)

    creds = Credentials(
        token=td.token,
        refresh_token=td.refresh_token,
        token_uri=td.token_uri,
        client_id=td.client_id,
        client_secret=td.client_secret,
        scopes=td.scopes,
    )

    if refresh_if_needed and creds.expired and creds.refresh_token:
        logger.info("Token expired; refreshing...")
        creds.refresh(Request())

        # Persist refresh token update back to same file for next runs.
        # Keep structure compatible with current token.json.
        updated = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
        with open(token_json_path, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2, default=list)

    return creds


def normalize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = meta or {}

    title = meta.get("title", "YouTube Short")
    description = meta.get("Deskripsi", meta.get("description", ""))
    tags = meta.get("tags", meta.get("Tag", ""))
    privacy = meta.get("privacy", "unlisted")
    category = meta.get("categoryId") or meta.get("category") or "22"
    language = meta.get("defaultLanguage") or meta.get("language") or ""
    made_for_kids = bool(meta.get("madeForKids", False))

    category_map = {
        "film": "1",
        "autos": "2",
        "music": "10",
        "pets": "15",
        "sports": "17",
        "travel": "19",
        "gaming": "20",
        "people": "22",
        "comedy": "23",
        "entertainment": "24",
        "news": "25",
        "howto": "26",
        "education": "27",
        "science": "28",
    }
    category_id = str(category).strip()
    if not category_id.isdigit():
        category_id = category_map.get(category_id.lower(), "22")

    if "#Shorts" not in description:
        description = f"{description}\n#Shorts".strip()

    if isinstance(tags, str):
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        tag_list = tags
    else:
        tag_list = []

    if "Shorts" not in tag_list:
        tag_list.append("Shorts")

    out = {
        "title": (title or "YouTube Short")[:100],
        "description": (description or "")[:5000],
        "tag_list": tag_list,
        "privacy": privacy,
        "category_id": category_id,
        "language": str(language).strip(),
        "made_for_kids": made_for_kids,
    }

    thumb = meta.get("Thumbnail", "") or meta.get("thumbnail", "")
    if thumb:
        out["thumbnail"] = thumb
    pinned_comment = meta.get("pinnedComment") or meta.get("pinned_comment")
    if pinned_comment:
        out["pinned_comment"] = str(pinned_comment).strip()

    return out


def upload_short(
    file_path: str,
    metadata: Optional[Dict[str, Any]] = None,
    token_json_path: str = "token.json",
) -> Dict[str, Any]:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Video file not found: {file_path}")

    creds = build_credentials(token_json_path)

    youtube = build("youtube", "v3", credentials=creds)
    norm = normalize_metadata(metadata or {})

    body = {
        "snippet": {
            "title": norm["title"],
            "description": norm["description"],
            "tags": norm["tag_list"],
            "categoryId": norm["category_id"],
        },
        "status": {
            "privacyStatus": norm["privacy"],
            "selfDeclaredMadeForKids": norm["made_for_kids"],
        },
    }
    if norm["language"]:
        body["snippet"]["defaultLanguage"] = norm["language"]
        body["snippet"]["defaultAudioLanguage"] = norm["language"]

    media = MediaFileUpload(
        file_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            logger.info("Upload progress: %s%%", progress)

    video_id = response["id"]
    upload_url = f"https://youtube.com/shorts/{video_id}"

    thumb = norm.get("thumbnail")
    if thumb and os.path.exists(thumb):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb, mimetype="image/jpeg"),
            ).execute()
        except Exception as e:
            logger.warning("Failed to set thumbnail: %s", e)

    pinned_comment = norm.get("pinned_comment")
    if pinned_comment:
        try:
            youtube.commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {
                            "snippet": {
                                "textOriginal": pinned_comment,
                            }
                        },
                    }
                },
            ).execute()
        except Exception as e:
            logger.warning("Failed to add pinned-comment text as top-level comment: %s", e)

    return {"video_id": video_id, "upload_url": upload_url}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--metadata-json", required=False, default="")

    args = parser.parse_args()

    meta = json.loads(args.metadata_json) if args.metadata_json else {}
    res = upload_short(args.file, metadata=meta, token_json_path=args.token)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    main()
