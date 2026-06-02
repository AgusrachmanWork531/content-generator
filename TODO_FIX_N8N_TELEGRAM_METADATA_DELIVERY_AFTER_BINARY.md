# TODO: Fix N8N Telegram Metadata Delivery After Binary Read

## Status: PLANNED

## Goal

Fix the final Telegram delivery flow in `n8n_node.json` so:

- `Prepare Telegram Payload` has valid JavaScript syntax.
- The final watermarked video is sent to Telegram.
- YouTube metadata is also sent to Telegram through `Send a text message`.
- Metadata is not lost after `Read Binary File`.

## Current Issues

### Issue 1: `Prepare Telegram Payload` Syntax Error

Current ending is malformed:

```js
return [{
  json: {
    chat_id,
    video_id,
    video_path: videoPath,
    caption,
    metadata_text,
    filename: watermarkedVideo.filename
  }
];
```

This causes a JavaScript parse error.

Correct ending:

```js
return [
  {
    json: {
      chat_id,
      video_id,
      video_path: videoPath,
      caption,
      metadata_text,
      filename: watermarkedVideo.filename
    }
  }
];
```

### Issue 2: Metadata May Not Reach `Send a text message`

`Read Binary File` can change item shape depending on n8n behavior/version. If the binary read node does not preserve all JSON fields, then `Send a text message` may not receive:

- `chat_id`
- `metadata_text`
- `caption`
- `video_id`
- `filename`

The workflow must explicitly preserve metadata after binary read or route the text message from the formatter node.

## Required Fix

### Part 1: Fix `Prepare Telegram Payload`

- [ ] Replace malformed return statement with valid n8n item array.
- [ ] Ensure output JSON includes:
  - `chat_id`
  - `video_id`
  - `video_path`
  - `caption`
  - `metadata_text`
  - `filename`

### Part 2: Make YouTube Metadata Text Complete

- [ ] Build `metadata_text` from `render_payload.youtube_metadata`.
- [ ] Include:
  - title
  - description
  - hashtags
  - thumbnail text if available
  - hook text
  - duration
  - viral score
  - clip type
  - source `video_id`
  - selected watermark filename

Suggested text format:

```text
✅ Render Watermark Selesai

🎬 Title:
{{ title }}

📝 Description:
{{ description }}

🏷 Hashtags:
{{ hashtags }}

🖼 Thumbnail Text:
{{ thumbnail_text }}

🪝 Hook:
{{ hook_text }}

⭐ Viral Score:
{{ viral_score }}

🎭 Clip Type:
{{ clip_type }}

⏱ Duration:
{{ duration }} detik

🔗 Source Video ID:
{{ video_id }}

📁 File:
{{ filename }}
```

### Part 3: Preserve Metadata After `Read Binary File`

Choose one of these approaches.

#### Option A: Add Code Node After `Read Binary File`

- [ ] Add node: `Merge Binary With Telegram Payload`
- [ ] Connect:

```text
Read Binary File -> Merge Binary With Telegram Payload
```

- [ ] Rehydrate JSON from `Prepare Telegram Payload`:

```js
const payload = $('Prepare Telegram Payload').first().json;

return $input.all().map(item => ({
  json: {
    ...payload,
    ...item.json
  },
  binary: item.binary
}));
```

- [ ] Then connect:

```text
Merge Binary With Telegram Payload -> Send a video
Merge Binary With Telegram Payload -> Send a text message
```

#### Option B: Branch Text Message Before `Read Binary File`

- [ ] Connect `Prepare Telegram Payload` directly to `Send a text message`.
- [ ] Also connect `Prepare Telegram Payload` to `Read Binary File`.
- [ ] Connect `Read Binary File` to `Send a video`.

Recommended: Option B, because metadata text does not depend on the binary file and is less fragile.

## Recommended Final Connection

```text
If Watermark Completed3
  true
    -> Get Watermark Result
    -> Prepare Telegram Payload
       -> Send a text message
       -> Read Binary File
          -> Send a video

  false
    -> Wait Watermark3
    -> Cek Status Watermark2
```

## Suggested `Prepare Telegram Payload` Code Ending

```js
return [
  {
    json: {
      chat_id,
      video_id,
      video_path: videoPath,
      caption,
      metadata_text,
      filename: watermarkedVideo.filename
    }
  }
];
```

## Suggested Metadata Builder

```js
const hookText = original.render_payload?.hook_3_5_seconds?.text || '-';
const thumbnailText = yt.thumbnail_text || '-';
const viralScore = original.render_payload?.viral_score ?? '-';
const clipType = original.render_payload?.clip_type || '-';
const duration = original.render_payload?.duration || original.render_payload?.calculated_duration || '-';
const hashtags = Array.isArray(yt.hashtags) ? yt.hashtags.join(' ') : '';

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
```

## Acceptance Criteria

- [ ] `Prepare Telegram Payload` JavaScript parses successfully.
- [ ] `n8n_node.json` remains valid JSON.
- [ ] Telegram receives the watermarked video.
- [ ] Telegram receives a separate text message containing YouTube metadata.
- [ ] Metadata message includes title, description, hashtags, hook, duration, viral score, clip type, and source `video_id`.
- [ ] Workflow does not hardcode `short_01_wm.mp4`.
- [ ] Video selection still uses dynamic result `files[]`.

## Validation Steps

- [ ] Validate workflow JSON:

```text
node -e "JSON.parse(require('fs').readFileSync('n8n_node.json','utf8')); console.log('json ok')"
```

- [ ] Validate `Prepare Telegram Payload` JavaScript:

```text
node -e "const fs=require('fs'); const wf=JSON.parse(fs.readFileSync('n8n_node.json','utf8')); const n=wf.nodes.find(n=>n.name==='Prepare Telegram Payload'); new Function(n.parameters.jsCode); console.log('js ok')"
```

- [ ] Run workflow with a completed watermark result.
- [ ] Confirm `Send a text message` receives `metadata_text`.
- [ ] Confirm `Send a video` receives binary property `data`.
