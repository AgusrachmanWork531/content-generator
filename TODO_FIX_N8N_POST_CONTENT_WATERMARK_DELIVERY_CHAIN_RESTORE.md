# TODO: Fix N8N Post Content Watermark Delivery Chain Restore

## Status

OPEN

## Goal

Fix `n8n_post_content.json` so the workflow continues after watermark completion and sends:

- YouTube metadata text to Telegram
- watermarked video to Telegram

Current workflow stops after watermark completes because the true branch of:

```text
If Watermark Completed2
```

is empty.

## File To Edit

Edit only:

```text
n8n_post_content.json
```

Do not edit:

```text
api_server.py
tools/media/free_viral_shorts.sh
external_packages/auto-captions/caption_generator.py
n8n_node.json
```

## Current Problem

Current connection:

```json
"If Watermark Completed2": {
  "main": [
    [],
    [
      {
        "node": "Wait Watermark2",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

This means:

- true branch does nothing
- workflow stops after watermark is completed
- final Telegram metadata is not sent
- final Telegram video is not sent

## Required Final Flow

After watermark is completed, the workflow must continue like this:

```text
If Watermark Completed2 true
-> Get Watermark Result
-> Prepare Telegram Payload
-> Send a text message
-> Download Watermark Video
-> Send a video
```

Important:

- `Send a text message` and `Download Watermark Video` should both receive output from `Prepare Telegram Payload`.
- `Download Watermark Video` should then connect to `Send a video`.
- Do not use `Read Binary File`.
- Download video using HTTP Request with `responseFormat = file`.

## Plan

1. Add missing final delivery nodes if they do not exist.
2. Wire `If Watermark Completed2` true branch to `Get Watermark Result`.
3. Wire `Get Watermark Result` to `Prepare Telegram Payload`.
4. Wire `Prepare Telegram Payload` to both:
   - `Send a text message`
   - `Download Watermark Video`
5. Wire `Download Watermark Video` to `Send a video`.
6. Preserve existing false branch:
   - `If Watermark Completed2` false branch must still go to `Wait Watermark2`.
7. Keep `Wait Watermark2 -> Cek Status Watermark2`.
8. Add subtitle path context to `Keep Subtitle Status Context1`.
9. Validate JSON and required connections.

## Step 1: Add `Get Watermark Result`

If the node does not exist, add this HTTP Request node:

```json
{
  "parameters": {
    "url": "=https://authentic-linguist-scoundrel.ngrok-free.dev/jobs/{{ $json.job_id }}/result",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "Bearer change-me"
        }
      ]
    },
    "options": {}
  },
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.3,
  "position": [
    6400,
    6176
  ],
  "id": "get-watermark-result-restored",
  "name": "Get Watermark Result"
}
```

## Step 2: Add `Prepare Telegram Payload`

If the node does not exist, add this Code node:

```json
{
  "parameters": {
    "jsCode": "// Prepare Telegram Payload\nconst original = $('Code in JavaScript2').first().json;\nconst result = $input.first().json;\n\nconst API_BASE_URL = 'https://authentic-linguist-scoundrel.ngrok-free.dev';\n\nconst chat_id = original.telegram?.chat_id;\nif (!chat_id) {\n  throw new Error('chat_id tidak ditemukan dari payload Telegram');\n}\n\nconst yt = original.render_payload?.youtube_metadata;\nif (!yt) {\n  throw new Error('youtube_metadata tidak ditemukan dari render_payload');\n}\n\nconst video_id = original.video_id;\nconst files = result.files || [];\n\nconst watermarkedVideo =\n  files.find(file =>\n    file.filename?.endsWith('.mp4') &&\n    (\n      file.filename.includes('_wm') ||\n      file.path?.includes('/watermarked/')\n    )\n  ) ||\n  files.find(file => file.filename?.endsWith('.mp4'));\n\nif (!watermarkedVideo) {\n  throw new Error(`File video watermark tidak ditemukan. files=${JSON.stringify(files)}`);\n}\n\nconst rawVideoPath =\n  watermarkedVideo.absolute_path ||\n  watermarkedVideo.file_path ||\n  watermarkedVideo.path;\n\nconst video_path = rawVideoPath?.startsWith('/')\n  ? rawVideoPath\n  : rawVideoPath\n    ? `/Users/agusrachman/Documents/Codex/content-short/storage/${rawVideoPath}`\n    : null;\n\nconst video_download_url =\n  watermarkedVideo.download_url ||\n  (watermarkedVideo.url ? `${API_BASE_URL}${watermarkedVideo.url}` : null);\n\nif (!video_download_url) {\n  throw new Error(`Download URL video tidak ditemukan: ${JSON.stringify(watermarkedVideo)}`);\n}\n\nconst hashtags = Array.isArray(yt.hashtags) ? yt.hashtags.join(' ') : '';\nconst hookText = original.render_payload?.hook_3_5_seconds?.text || '-';\nconst thumbnailText = yt.thumbnail_text || '-';\nconst viralScore = original.render_payload?.viral_score ?? '-';\nconst clipType = original.render_payload?.clip_type || '-';\nconst duration =\n  original.render_payload?.duration ||\n  original.render_payload?.calculated_duration ||\n  '-';\n\nconst caption = [\n  yt.title || 'Video pendek',\n  hashtags\n].filter(Boolean).join('\\n\\n').slice(0, 1024);\n\nconst metadata_text = [\n  '✅ Render Watermark Selesai',\n  '',\n  `🎬 Title:\\n${yt.title || '-'}`,\n  '',\n  `📝 Description:\\n${yt.description || '-'}`,\n  '',\n  `🏷 Hashtags:\\n${hashtags || '-'}`,\n  '',\n  `🖼 Thumbnail Text:\\n${thumbnailText}`,\n  '',\n  `🪝 Hook:\\n${hookText}`,\n  '',\n  `⭐ Viral Score:\\n${viralScore}`,\n  '',\n  `🎭 Clip Type:\\n${clipType}`,\n  '',\n  `⏱ Duration:\\n${duration} detik`,\n  '',\n  `🔗 Source Video ID:\\n${video_id}`,\n  '',\n  `📁 File:\\n${watermarkedVideo.filename || video_path || video_download_url}`,\n  '',\n  `⬇️ Download:\\n${video_download_url}`\n].join('\\n');\n\nreturn [\n  {\n    json: {\n      chat_id,\n      video_id,\n      video_path,\n      video_download_url,\n      caption,\n      metadata_text,\n      filename: watermarkedVideo.filename || video_path || video_download_url\n    }\n  }\n];"
  },
  "type": "n8n-nodes-base.code",
  "typeVersion": 2,
  "position": [
    6624,
    6176
  ],
  "id": "prepare-telegram-payload-restored",
  "name": "Prepare Telegram Payload"
}
```

## Step 3: Add `Send a text message`

If the node does not exist, add this Telegram node:

```json
{
  "parameters": {
    "chatId": "={{ $json.chat_id }}",
    "text": "={{ $json.metadata_text }}",
    "additionalFields": {
      "parse_mode": "Markdown"
    }
  },
  "type": "n8n-nodes-base.telegram",
  "typeVersion": 1.2,
  "position": [
    6832,
    6288
  ],
  "id": "send-text-message-restored",
  "name": "Send a text message",
  "webhookId": "send-text-message-restored-webhook",
  "credentials": {
    "telegramApi": {
      "id": "wo2KtQA3GKUjikub",
      "name": "Telegram account"
    }
  }
}
```

## Step 4: Add `Download Watermark Video`

If the node does not exist, add this HTTP Request node:

```json
{
  "parameters": {
    "url": "={{ $json.video_download_url }}",
    "authentication": "genericCredentialType",
    "genericAuthType": "httpBearerAuth",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {}
      ]
    },
    "options": {
      "response": {
        "response": {
          "responseFormat": "file"
        }
      }
    }
  },
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.3,
  "position": [
    6832,
    6080
  ],
  "id": "download-watermark-video-restored",
  "name": "Download Watermark Video",
  "credentials": {
    "httpBearerAuth": {
      "id": "qnh8bEUvqFLgPjIQ",
      "name": "Bearer Auth account"
    }
  }
}
```

## Step 5: Add `Send a video`

If the node does not exist, add this Telegram node:

```json
{
  "parameters": {
    "operation": "sendVideo",
    "chatId": "={{ $('Prepare Telegram Payload').first().json.chat_id }}",
    "binaryData": true,
    "additionalFields": {
      "caption": "={{ $('Prepare Telegram Payload').first().json.caption }}"
    }
  },
  "type": "n8n-nodes-base.telegram",
  "typeVersion": 1.2,
  "position": [
    7040,
    6080
  ],
  "id": "send-video-restored",
  "name": "Send a video",
  "webhookId": "send-video-restored-webhook",
  "credentials": {
    "telegramApi": {
      "id": "wo2KtQA3GKUjikub",
      "name": "Telegram account"
    }
  }
}
```

## Step 6: Required Connections

Set these connections exactly:

```json
"If Watermark Completed2": {
  "main": [
    [
      {
        "node": "Get Watermark Result",
        "type": "main",
        "index": 0
      }
    ],
    [
      {
        "node": "Wait Watermark2",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

```json
"Get Watermark Result": {
  "main": [
    [
      {
        "node": "Prepare Telegram Payload",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

```json
"Prepare Telegram Payload": {
  "main": [
    [
      {
        "node": "Send a text message",
        "type": "main",
        "index": 0
      },
      {
        "node": "Download Watermark Video",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

```json
"Download Watermark Video": {
  "main": [
    [
      {
        "node": "Send a video",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Do not connect `Send a text message` to `Download Watermark Video`.

Both must receive the same payload from `Prepare Telegram Payload`.

## Step 7: Preserve Subtitle Context

Update `Keep Subtitle Status Context1` so it keeps the subtitle path fields from `Remap Subtitle Job ID1`.

Add these fields inside returned `json`:

```js
subtitle_video_path: ctx.subtitle_video_path,
subtitle_fallback_video_path: ctx.subtitle_fallback_video_path,
clip_index: ctx.clip_index,
clip_number: ctx.clip_number
```

Full replacement code:

```js
const ctx = $('Remap Subtitle Job ID1').first().json;

return $input.all().map(item => {
  const body = item.json.body || item.json;

  return {
    json: {
      ...body,
      job_id: body.job_id || ctx.job_id,
      step: body.step || ctx.step || 'subtitle',
      status_url: body.status_url || ctx.status_url || `/subtitle/jobs/${ctx.job_id}`,
      result_url: body.result_url || ctx.result_url || `/subtitle/jobs/${ctx.job_id}`,
      source: ctx.source,
      video_id: ctx.video_id,
      subtitle_video_path: ctx.subtitle_video_path,
      subtitle_fallback_video_path: ctx.subtitle_fallback_video_path,
      clip_index: ctx.clip_index,
      clip_number: ctx.clip_number
    }
  };
});
```

## Validation Commands

Run JSON validation:

```bash
python3 -m json.tool n8n_post_content.json > /tmp/n8n_post_content.validated.json
```

Run connection validation:

```bash
python3 - <<'PY'
import json
from collections import Counter

data = json.load(open('n8n_post_content.json'))
names = [node['name'] for node in data['nodes']]

duplicates = [name for name, count in Counter(names).items() if count > 1]
if duplicates:
    raise SystemExit(f'Duplicate node names: {duplicates}')

connections = data.get('connections', {})

missing = []
for source, config in connections.items():
    if source not in names:
        missing.append(f'Missing source node: {source}')
    for group in config.get('main', []):
        for edge in group:
            if edge['node'] not in names:
                missing.append(f"Missing target node: {source} -> {edge['node']}")

if missing:
    raise SystemExit('\n'.join(missing))

print('OK: no duplicate node names and no broken connections')
PY
```

Run final delivery validation:

```bash
python3 - <<'PY'
import json

data = json.load(open('n8n_post_content.json'))
names = {node['name'] for node in data['nodes']}
connections = data.get('connections', {})

required_nodes = {
    'If Watermark Completed2',
    'Get Watermark Result',
    'Prepare Telegram Payload',
    'Send a text message',
    'Download Watermark Video',
    'Send a video',
}

missing_nodes = required_nodes - names
if missing_nodes:
    raise SystemExit(f'Missing final delivery nodes: {sorted(missing_nodes)}')

def targets(source):
    result = []
    for group in connections.get(source, {}).get('main', []):
        result.extend(edge['node'] for edge in group)
    return result

checks = {
    'If Watermark Completed2': ['Get Watermark Result', 'Wait Watermark2'],
    'Get Watermark Result': ['Prepare Telegram Payload'],
    'Prepare Telegram Payload': ['Send a text message', 'Download Watermark Video'],
    'Download Watermark Video': ['Send a video'],
}

for source, expected_targets in checks.items():
    actual = targets(source)
    for expected in expected_targets:
        if expected not in actual:
            raise SystemExit(f'{source} must connect to {expected}; actual={actual}')

print('OK: final watermark delivery chain restored')
PY
```

Run subtitle context validation:

```bash
python3 - <<'PY'
import json

data = json.load(open('n8n_post_content.json'))
node = next(n for n in data['nodes'] if n['name'] == 'Keep Subtitle Status Context1')
code = node['parameters']['jsCode']

required = [
    'subtitle_video_path',
    'subtitle_fallback_video_path',
    'clip_index',
    'clip_number',
]

missing = [field for field in required if field not in code]
if missing:
    raise SystemExit(f'Keep Subtitle Status Context1 is missing fields: {missing}')

print('OK: subtitle path context is preserved')
PY
```

## Acceptance Criteria

- `n8n_post_content.json` is valid JSON.
- No duplicate node names.
- No broken connections.
- `If Watermark Completed2` true branch connects to `Get Watermark Result`.
- `If Watermark Completed2` false branch still connects to `Wait Watermark2`.
- `Get Watermark Result` connects to `Prepare Telegram Payload`.
- `Prepare Telegram Payload` connects to both:
  - `Send a text message`
  - `Download Watermark Video`
- `Download Watermark Video` connects to `Send a video`.
- `Send a text message` uses:

```text
chatId = ={{ $json.chat_id }}
text = ={{ $json.metadata_text }}
parse_mode = Markdown
```

- `Download Watermark Video` uses:

```text
url = ={{ $json.video_download_url }}
responseFormat = file
```

- `Send a video` uses:

```text
chatId = ={{ $('Prepare Telegram Payload').first().json.chat_id }}
caption = ={{ $('Prepare Telegram Payload').first().json.caption }}
binaryData = true
```

- `Keep Subtitle Status Context1` preserves subtitle path context fields.

