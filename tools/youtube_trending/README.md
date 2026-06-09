# YouTube Trending Discovery

Fetch trending YouTube videos by region and category, rank them with engagement metrics, and emit JSON ready for the long-video-to-short-clip pipeline.

## Auth

Preferred auth is `YOUTUBE_API_KEY` or `API_KEY_YOUTUBE`:

```bash
export YOUTUBE_API_KEY="your-api-key"
```

The CLI also loads `.env` automatically and will use:

```text
API_KEY_YOUTUBE=your-api-key
```

If `YOUTUBE_API_KEY` is empty, the CLI falls back to OAuth `token.json`. It checks:

```text
token.json
.local-secrets/token.json
/Users/agusrachman/Documents/Docker/n8n/download-clip/token.json
```

The token must include:

```text
https://www.googleapis.com/auth/youtube.readonly
```

## Run

```bash
python3 tools/youtube_trending/fetch_youtube_trending.py \
  --region ID \
  --categories 24,23,22 \
  --max-results 50 \
  --min-views 50000 \
  --min-comments 100 \
  --limit 30
```

The command writes JSON to stdout. Process logs go to stderr.

## Save Output

```bash
python3 tools/youtube_trending/fetch_youtube_trending.py \
  --region ID \
  --categories 24,23,22 \
  --save storage/youtube-trending/trending_ID_entertainment.json
```

The output folder is created automatically.

## API

When `api_server.py` is running, call:

```bash
curl -sS -X POST http://127.0.0.1:8088/youtube/trending/category \
  -H 'Authorization: Bearer change-me' \
  -H 'Content-Type: application/json' \
  -d '{
    "regionCode": "ID",
    "categories": ["23"],
    "maxResultsPerCategory": 5,
    "minViewCount": 2000,
    "minCommentCount": 0,
    "preferredDurationMinutes": {
      "min": 0.5,
      "max": 1.5
    },
    "limit": 3
  }'
```

For ngrok, replace the base URL with the public API URL:

```text
https://authentic-linguist-scoundrel.ngrok-free.dev/youtube/trending/category
```

## Output

Top-level response:

```json
{
  "status": "success",
  "source_type": "youtube_trending_category",
  "regionCode": "ID",
  "total_categories_scanned": 3,
  "total_videos_found": 0,
  "total_videos_after_filter": 0,
  "sortBy": "trend_score",
  "items": [],
  "pipeline_payloads": []
}
```

Each `pipeline_payloads` item is ready for the clip extractor:

```json
{
  "source": "lo6KE0Kcvoc",
  "video_id": "lo6KE0Kcvoc",
  "num_clips": 3,
  "quality": "1080",
  "languages": "id,en",
  "metadata": {
    "rank": 1,
    "title": "string",
    "channel_title": "string",
    "category_id": "24",
    "category_name": "Entertainment",
    "trend_score": 123456,
    "view_count": 100000,
    "comment_count": 100
  }
}
```

`source` and `video_id` are always the 11-character YouTube video ID, not a full YouTube URL.

## Category IDs

```text
1  Film & Animation
2  Autos & Vehicles
10 Music
15 Pets & Animals
17 Sports
19 Travel & Events
20 Gaming
22 People & Blogs
23 Comedy
24 Entertainment
25 News & Politics
26 Howto & Style
27 Education
28 Science & Technology
```

## Trend Score

```text
trend_score =
(view_count * 0.6) +
(like_count * 3) +
(comment_count * 8) +
recency_bonus
```

Recency bonus:

```text
<= 24 hours: 50000
<= 3 days:   25000
<= 7 days:   10000
> 7 days:    0
```

Results are sorted by `trend_score`, then `comment_count`, then `view_count`, then newest `published_at`.
