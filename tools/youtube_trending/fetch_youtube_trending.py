#!/usr/bin/env python3
"""Fetch YouTube trending videos by region and category.

The module is intentionally self-contained so it can be used from CLI and
imported by the FastAPI server without changing the existing pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


SOURCE_TYPE = "youtube_trending_category"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/videos"
REPO_ROOT = Path(__file__).resolve().parents[2]

CATEGORY_MAP = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "19": "Travel & Events",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
}

DEFAULT_CONFIG = {
    "regionCode": "ID",
    "categories": ["24", "23", "22"],
    "maxResultsPerCategory": 50,
    "minViewCount": 50000,
    "minCommentCount": 100,
    "preferredDurationMinutes": {
        "min": 3,
        "max": 60,
    },
    "sortBy": "trend_score",
    "limit": 30,
    "num_clips": 3,
    "quality": "1080",
    "languages": "id,en",
}


class TrendingError(Exception):
    """Expected error that should be rendered as a JSON response."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


@dataclass
class AuthContext:
    mode: str
    api_key: Optional[str] = None
    youtube: Any = None


def log(message: str) -> None:
    print(f"[YouTubeTrending] {message}", file=sys.stderr)


def load_dotenv_if_present() -> None:
    """Load simple KEY=VALUE pairs from .env without overriding exported env."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def error_response(message: str, details: str = "") -> dict[str, Any]:
    response: dict[str, Any] = {
        "status": "failed",
        "message": message,
    }
    if details:
        response["details"] = details
    return response


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_duration_iso(duration_iso: str) -> tuple[int, float]:
    match = re.fullmatch(
        r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        duration_iso or "",
    )
    if not match:
        raise TrendingError("Duration ISO failed to parse", duration_iso or "<empty>")

    hours = parse_int(match.group("hours"))
    minutes = parse_int(match.group("minutes"))
    seconds = parse_int(match.group("seconds"))
    total_seconds = (hours * 3600) + (minutes * 60) + seconds
    if total_seconds <= 0:
        raise TrendingError("Duration ISO failed to parse", duration_iso)
    return total_seconds, round(total_seconds / 60, 2)


def parse_published_at(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrendingError("published_at failed to parse", value) from exc


def calculate_trend_score(video: dict[str, Any]) -> int:
    published_at = parse_published_at(video["published_at"])
    age_seconds = (datetime.now(timezone.utc) - published_at).total_seconds()
    age_days = age_seconds / 86400

    if age_days <= 1:
        recency_bonus = 50000
    elif age_days <= 3:
        recency_bonus = 25000
    elif age_days <= 7:
        recency_bonus = 10000
    else:
        recency_bonus = 0

    score = (
        (video["view_count"] * 0.6)
        + (video["like_count"] * 3)
        + (video["comment_count"] * 8)
        + recency_bonus
    )
    return int(round(score))


def token_candidates() -> list[Path]:
    return [
        REPO_ROOT / "token.json",
        REPO_ROOT / ".local-secrets/token.json",
        Path("/Users/agusrachman/Documents/Docker/n8n/download-clip/token.json"),
    ]


def build_auth_context() -> AuthContext:
    load_dotenv_if_present()
    api_key = (
        os.environ.get("YOUTUBE_API_KEY", "").strip()
        or os.environ.get("API_KEY_YOUTUBE", "").strip()
    )
    if api_key:
        return AuthContext(mode="api_key", api_key=api_key)

    existing_token_paths = [path for path in token_candidates() if path.exists()]
    if not existing_token_paths:
        raise TrendingError(
            "YOUTUBE_API_KEY or token.json with youtube.readonly scope is required",
            "Checked: " + ", ".join(str(path) for path in token_candidates()),
        )

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:
        raise TrendingError("Google API dependencies are not available", str(exc)) from exc

    failures = []
    for token_path in existing_token_paths:
        try:
            creds_data = json.loads(token_path.read_text(encoding="utf-8"))
            scopes = creds_data.get("scopes") or []
            if YOUTUBE_READONLY_SCOPE not in scopes:
                failures.append(f"{token_path}: missing youtube.readonly scope")
                continue

            creds = Credentials(
                token=creds_data.get("token"),
                refresh_token=creds_data.get("refresh_token"),
                token_uri=creds_data.get("token_uri"),
                client_id=creds_data.get("client_id"),
                client_secret=creds_data.get("client_secret"),
                scopes=scopes,
            )

            if creds.refresh_token:
                creds.refresh(Request())
                creds_data["token"] = creds.token
                creds_data["refresh_token"] = creds.refresh_token
                token_path.write_text(
                    json.dumps(creds_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            elif creds.expired:
                failures.append(f"{token_path}: expired token without refresh_token")
                continue

            youtube = build("youtube", "v3", credentials=creds)
            return AuthContext(mode="oauth_token", youtube=youtube)
        except Exception as exc:
            failures.append(f"{token_path}: {exc.__class__.__name__}")

    raise TrendingError(
        "YOUTUBE_API_KEY or valid token.json with youtube.readonly scope is required",
        "; ".join(failures),
    )


def fetch_category_with_api_key(
    auth: AuthContext,
    region_code: str,
    category_id: str,
    max_results: int,
) -> list[dict[str, Any]]:
    params = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region_code,
        "videoCategoryId": category_id,
        "maxResults": str(max_results),
        "key": auth.api_key or "",
    }
    url = f"{YOUTUBE_API_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise TrendingError("YouTube API request failed", details) from exc
    except urllib.error.URLError as exc:
        raise TrendingError("Network error while calling YouTube API", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise TrendingError("JSON parse error from YouTube API", str(exc)) from exc

    return payload.get("items") or []


def fetch_category_with_oauth(
    auth: AuthContext,
    region_code: str,
    category_id: str,
    max_results: int,
) -> list[dict[str, Any]]:
    try:
        response = (
            auth.youtube.videos()
            .list(
                part="snippet,statistics,contentDetails",
                chart="mostPopular",
                regionCode=region_code,
                videoCategoryId=category_id,
                maxResults=max_results,
            )
            .execute()
        )
    except Exception as exc:
        raise TrendingError("YouTube API request failed", str(exc)) from exc
    return response.get("items") or []


def fetch_category(
    auth: AuthContext,
    region_code: str,
    category_id: str,
    max_results: int,
) -> list[dict[str, Any]]:
    if auth.mode == "api_key":
        return fetch_category_with_api_key(auth, region_code, category_id, max_results)
    return fetch_category_with_oauth(auth, region_code, category_id, max_results)


def normalize_video(item: dict[str, Any], category_id: str) -> dict[str, Any]:
    snippet = item.get("snippet") or {}
    statistics = item.get("statistics") or {}
    content_details = item.get("contentDetails") or {}
    thumbnails = snippet.get("thumbnails") or {}
    thumbnail = (
        thumbnails.get("maxres")
        or thumbnails.get("standard")
        or thumbnails.get("high")
        or thumbnails.get("medium")
        or thumbnails.get("default")
        or {}
    )

    video_id = item.get("id") or ""
    title = snippet.get("title") or ""
    duration_iso = content_details.get("duration") or ""
    duration_seconds, duration_minutes = parse_duration_iso(duration_iso)

    video = {
        "video_id": video_id,
        "title": title,
        "description": snippet.get("description") or "",
        "channel_id": snippet.get("channelId") or "",
        "channel_title": snippet.get("channelTitle") or "",
        "published_at": snippet.get("publishedAt") or "",
        "category_id": category_id,
        "category_name": CATEGORY_MAP[category_id],
        "duration_iso": duration_iso,
        "duration_seconds": duration_seconds,
        "duration_minutes": duration_minutes,
        "view_count": parse_int(statistics.get("viewCount")),
        "like_count": parse_int(statistics.get("likeCount")),
        "comment_count": parse_int(statistics.get("commentCount")),
        "thumbnail_url": thumbnail.get("url") or "",
        "source_type": SOURCE_TYPE,
    }
    video["trend_score"] = calculate_trend_score(video)
    return video


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for key, value in (config or {}).items():
        if key == "preferredDurationMinutes" and isinstance(value, dict):
            merged[key].update(value)
        elif value is not None:
            merged[key] = value

    categories = [str(item).strip() for item in merged["categories"] if str(item).strip()]
    invalid = [category for category in categories if category not in CATEGORY_MAP]
    if invalid:
        raise TrendingError("Category invalid", ",".join(invalid))

    region_code = str(merged["regionCode"]).strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", region_code):
        raise TrendingError("Region invalid", region_code)

    merged["regionCode"] = region_code
    merged["categories"] = categories
    merged["maxResultsPerCategory"] = max(1, min(50, parse_int(merged["maxResultsPerCategory"], 50)))
    merged["minViewCount"] = max(0, parse_int(merged["minViewCount"], 0))
    merged["minCommentCount"] = max(0, parse_int(merged["minCommentCount"], 0))
    merged["limit"] = max(1, parse_int(merged["limit"], 30))
    merged["num_clips"] = max(1, parse_int(merged["num_clips"], 3))
    merged["quality"] = str(merged["quality"])
    merged["languages"] = str(merged["languages"])
    return merged


def build_pipeline_payload(video: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": video["video_id"],
        "video_id": video["video_id"],
        "num_clips": config["num_clips"],
        "quality": config["quality"],
        "languages": config["languages"],
        "metadata": {
            "rank": video["rank"],
            "title": video["title"],
            "channel_title": video["channel_title"],
            "category_id": video["category_id"],
            "category_name": video["category_name"],
            "trend_score": video["trend_score"],
            "view_count": video["view_count"],
            "comment_count": video["comment_count"],
        },
    }


def discover_youtube_trending(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    try:
        cfg = validate_config(config or {})
        auth = build_auth_context()
        region_code = cfg["regionCode"]
        categories = cfg["categories"]
        duration_min = float(cfg["preferredDurationMinutes"]["min"])
        duration_max = float(cfg["preferredDurationMinutes"]["max"])

        log("Starting fetch trending videos")
        log(f"Region: {region_code}")
        log(f"Categories: {','.join(categories)}")

        total_videos_found = 0
        videos_by_id: dict[str, dict[str, Any]] = {}

        for category_id in categories:
            log(f"Fetching category {category_id} - {CATEGORY_MAP[category_id]}")
            items = fetch_category(auth, region_code, category_id, cfg["maxResultsPerCategory"])
            total_videos_found += len(items)
            log(f"Found {len(items)} videos from category {category_id}")

            for item in items:
                video = normalize_video(item, category_id)
                if not video["video_id"] or not video["title"]:
                    continue
                if video["video_id"] in videos_by_id:
                    continue
                if video["view_count"] < cfg["minViewCount"]:
                    continue
                if video["comment_count"] < cfg["minCommentCount"]:
                    continue
                if video["duration_minutes"] < duration_min or video["duration_minutes"] > duration_max:
                    continue
                videos_by_id[video["video_id"]] = video

        log("Filtering videos")
        selected = list(videos_by_id.values())
        log("Ranking videos by trend_score")
        selected.sort(
            key=lambda video: (
                video["trend_score"],
                video["comment_count"],
                video["view_count"],
                parse_published_at(video["published_at"]),
            ),
            reverse=True,
        )
        selected = selected[: cfg["limit"]]

        for index, video in enumerate(selected, start=1):
            video["rank"] = index

        response = {
            "status": "success",
            "source_type": SOURCE_TYPE,
            "regionCode": region_code,
            "total_categories_scanned": len(categories),
            "total_videos_found": total_videos_found,
            "total_videos_after_filter": len(videos_by_id),
            "sortBy": cfg["sortBy"],
            "items": selected,
            "pipeline_payloads": [build_pipeline_payload(video, cfg) for video in selected],
        }
        log(f"Done. Total selected: {len(selected)}")
        return response
    except TrendingError as exc:
        return error_response(exc.message, exc.details)
    except Exception as exc:
        return error_response("Unexpected error", str(exc))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch YouTube trending videos by category.")
    parser.add_argument("--region", default=DEFAULT_CONFIG["regionCode"])
    parser.add_argument("--categories", default=",".join(DEFAULT_CONFIG["categories"]))
    parser.add_argument("--max-results", type=int, default=DEFAULT_CONFIG["maxResultsPerCategory"])
    parser.add_argument("--min-views", type=int, default=DEFAULT_CONFIG["minViewCount"])
    parser.add_argument("--min-comments", type=int, default=DEFAULT_CONFIG["minCommentCount"])
    parser.add_argument("--duration-min", type=float, default=DEFAULT_CONFIG["preferredDurationMinutes"]["min"])
    parser.add_argument("--duration-max", type=float, default=DEFAULT_CONFIG["preferredDurationMinutes"]["max"])
    parser.add_argument("--limit", type=int, default=DEFAULT_CONFIG["limit"])
    parser.add_argument("--num-clips", type=int, default=DEFAULT_CONFIG["num_clips"])
    parser.add_argument("--quality", default=DEFAULT_CONFIG["quality"])
    parser.add_argument("--languages", default=DEFAULT_CONFIG["languages"])
    parser.add_argument("--save", default="")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "regionCode": args.region,
        "categories": [item.strip() for item in args.categories.split(",") if item.strip()],
        "maxResultsPerCategory": args.max_results,
        "minViewCount": args.min_views,
        "minCommentCount": args.min_comments,
        "preferredDurationMinutes": {
            "min": args.duration_min,
            "max": args.duration_max,
        },
        "limit": args.limit,
        "num_clips": args.num_clips,
        "quality": args.quality,
        "languages": args.languages,
    }


def main() -> int:
    args = parse_args()
    result = discover_youtube_trending(config_from_args(args))
    output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.save:
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(output + "\n", encoding="utf-8")

    print(output)
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
