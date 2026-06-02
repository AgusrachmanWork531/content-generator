# TODO: Simple Fix N8N Telegram Metadata Delivery

## Status

PLANNED

## File To Edit

`n8n_node.json`

## Goal

Fix the final Telegram delivery flow so:

- `Prepare Telegram Payload` JavaScript has no syntax error.
- Telegram receives the watermarked video.
- Telegram receives a separate message containing YouTube metadata.
- Video filename is selected dynamically from `files[]`, not hardcoded.

## Do These Steps Only

### Step 1: Find Node

In `n8n_node.json`, find the node:

```text
"name": "Prepare Telegram Payload"
```

Inside it, edit only:

```text
parameters.jsCode
```

### Step 2: Replace The Whole `jsCode`

Replace the entire `jsCode` value for `Prepare Telegram Payload` with this code:

```js
// Prepare Telegram Payload
const original = $('Code in JavaScript3').first().json;
const result = $input.first().json;

const chat_id = original.telegram?.chat_id;
if (!chat_id) {
  throw new Error('chat_id tidak ditemukan dari payload Telegram');
}

const yt = original.render_payload?.youtube_metadata;
if (!yt) {
  throw new Error('youtube_metadata tidak ditemukan dari render_payload');
}

const video_id = original.video_id;
const files = result.files || [];

const watermarkedVideo =
  files.find(file =>
    file.filename?.endsWith('.mp4') &&
    (
      file.filename.includes('_wm') ||
      file.path?.includes('/watermarked/')
    )
  ) ||
  files.find(file => file.filename?.endsWith('.mp4'));

if (!watermarkedVideo) {
  throw new Error(`File video watermark tidak ditemukan. files=${JSON.stringify(files)}`);
}

const videoPath =
  watermarkedVideo.path ||
  watermarkedVideo.file_path ||
  watermarkedVideo.absolute_path;

if (!videoPath) {
  throw new Error(`Path video tidak ditemukan dari file: ${JSON.stringify(watermarkedVideo)}`);
}

const hashtags = Array.isArray(yt.hashtags) ? yt.hashtags.join(' ') : '';
const hookText = original.render_payload?.hook_3_5_seconds?.text || '-';
const thumbnailText = yt.thumbnail_text || '-';
const viralScore = original.render_payload?.viral_score ?? '-';
const clipType = original.render_payload?.clip_type || '-';
const duration =
  original.render_payload?.duration ||
  original.render_payload?.calculated_duration ||
  '-';

const caption = [
  yt.title || 'Video pendek',
  hashtags
].filter(Boolean).join('\n\n').slice(0, 1024);

const metadata_text = [
  '✅ Render Watermark Selesai',
  '',
  `🎬 Title:\n${yt.title || '-'}`,
  '',
  `📝 Description:\n${yt.description || '-'}`,
  '',
  `🏷 Hashtags:\n${hashtags || '-'}`,
  '',
  `🖼 Thumbnail Text:\n${thumbnailText}`,
  '',
  `🪝 Hook:\n${hookText}`,
  '',
  `⭐ Viral Score:\n${viralScore}`,
  '',
  `🎭 Clip Type:\n${clipType}`,
  '',
  `⏱ Duration:\n${duration} detik`,
  '',
  `🔗 Source Video ID:\n${video_id}`,
  '',
  `📁 File:\n${watermarkedVideo.filename || videoPath}`
].join('\n');

return [
  {
    json: {
      chat_id,
      video_id,
      video_path: videoPath,
      caption,
      metadata_text,
      filename: watermarkedVideo.filename || videoPath
    }
  }
];
```

Important:

- Do not change the dynamic `files[]` selection.
- Do not hardcode `short_01_wm.mp4`.

### Step 3: Check Connections

Make sure this connection exists:

```text
Prepare Telegram Payload -> Send a text message
Prepare Telegram Payload -> Read Binary File
Read Binary File -> Send a video
```

Expected JSON connection:

```json
"Prepare Telegram Payload": {
  "main": [
    [
      {
        "node": "Read Binary File",
        "type": "main",
        "index": 0
      },
      {
        "node": "Send a text message",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

### Step 4: Check `Read Binary File`

Make sure `Read Binary File` uses:

```json
"fileName": "={{ $json.video_path }}",
"dataPropertyName": "data"
```

### Step 5: Check `Send a text message`

Make sure `Send a text message` uses:

```json
"chatId": "={{ $json.chat_id }}",
"text": "={{ $json.metadata_text }}"
```

### Step 6: Check `Send a video`

Make sure `Send a video` uses:

```json
"operation": "sendVideo",
"chatId": "={{ $json.chat_id }}",
"binaryData": true
```

If the node supports a binary property field, set it to:

```text
data
```

## Validation Commands

Run these commands from repo root.

### Validate JSON

```bash
node -e "JSON.parse(require('fs').readFileSync('n8n_node.json','utf8')); console.log('json ok')"
```

Expected:

```text
json ok
```

### Validate Prepare Telegram Payload JS

```bash
node -e "const fs=require('fs'); const wf=JSON.parse(fs.readFileSync('n8n_node.json','utf8')); const n=wf.nodes.find(n=>n.name==='Prepare Telegram Payload'); new Function(n.parameters.jsCode); console.log('js ok')"
```

Expected:

```text
js ok
```

## Acceptance Criteria

- [ ] `n8n_node.json` is valid JSON.
- [ ] `Prepare Telegram Payload` JavaScript parses successfully.
- [ ] `metadata_text` includes title, description, hashtags, thumbnail text, hook, viral score, clip type, duration, source video id, and file.
- [ ] `Send a text message` receives metadata directly from `Prepare Telegram Payload`.
- [ ] `Read Binary File` receives `video_path`.
- [ ] `Send a video` receives the binary video.
- [ ] No code hardcodes `short_01_wm.mp4` for the final Telegram video.
