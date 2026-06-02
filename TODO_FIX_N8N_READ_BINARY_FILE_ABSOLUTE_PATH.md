# TODO: Fix N8N Read Binary File Absolute Path

## Status

PLANNED

## Problem

`Read Binary File` fails with:

```text
The file "free-viral-shorts/0nr3B0Zg5Y8/watermarked/short_01_wm.mp4" could not be accessed.
```

The path from `/jobs/{job_id}/result` is relative to `storage`, but `Read Binary File` needs a filesystem path that n8n can access.

## File To Edit

```text
n8n_node.json
```

## Goal

Make `Prepare Telegram Payload` output an absolute `video_path`:

```text
/Users/agusrachman/Documents/Codex/content-short/storage/free-viral-shorts/.../watermarked/...mp4
```

Do not hardcode `short_01_wm.mp4`. Keep selecting the final video dynamically from `files[]`.

## Step 1: Find Node

Find:

```text
"name": "Prepare Telegram Payload"
```

Edit only:

```text
parameters.jsCode
```

## Step 2: Add Storage Base Path

Near the top, after:

```js
const result = $input.first().json;
```

Add:

```js
const STORAGE_BASE_DIR = '/Users/agusrachman/Documents/Codex/content-short/storage';
```

## Step 3: Replace Video Path Logic

Find current code:

```js
const videoPath =
  watermarkedVideo.path ||
  watermarkedVideo.file_path ||
  watermarkedVideo.absolute_path;

if (!videoPath) {
  throw new Error(`Path video tidak ditemukan dari file: ${JSON.stringify(watermarkedVideo)}`);
}
```

Replace with:

```js
const rawVideoPath =
  watermarkedVideo.absolute_path ||
  watermarkedVideo.file_path ||
  watermarkedVideo.path;

if (!rawVideoPath) {
  throw new Error(`Path video tidak ditemukan dari file: ${JSON.stringify(watermarkedVideo)}`);
}

const videoPath = rawVideoPath.startsWith('/')
  ? rawVideoPath
  : `${STORAGE_BASE_DIR}/${rawVideoPath}`;
```

## Step 4: Keep Dynamic Video Selection

Do not change this logic:

```js
const watermarkedVideo =
  files.find(file =>
    file.filename?.endsWith('.mp4') &&
    (
      file.filename.includes('_wm') ||
      file.path?.includes('/watermarked/')
    )
  ) ||
  files.find(file => file.filename?.endsWith('.mp4'));
```

## Step 5: Check `Read Binary File`

Make sure the node uses:

```json
"filePath": "={{ $json.video_path }}"
```

If the node supports a binary property name, set it to:

```json
"dataPropertyName": "data"
```

## Step 6: Check `Send a video`

Make sure the node uses:

```json
"operation": "sendVideo",
"chatId": "={{ $json.chat_id }}",
"binaryData": true
```

If the node supports binary property selection, set it to:

```text
data
```

## Expected Output From Prepare Telegram Payload

Before fix:

```text
video_path = free-viral-shorts/0nr3B0Zg5Y8/watermarked/short_01_wm.mp4
```

After fix:

```text
video_path = /Users/agusrachman/Documents/Codex/content-short/storage/free-viral-shorts/0nr3B0Zg5Y8/watermarked/short_01_wm.mp4
```

## Validation Commands

Run from repo root.

### Validate JSON

```bash
node -e "JSON.parse(require('fs').readFileSync('n8n_node.json','utf8')); console.log('json ok')"
```

Expected:

```text
json ok
```

### Validate JavaScript

```bash
node -e "const fs=require('fs'); const wf=JSON.parse(fs.readFileSync('n8n_node.json','utf8')); const n=wf.nodes.find(n=>n.name==='Prepare Telegram Payload'); new Function(n.parameters.jsCode); console.log('js ok')"
```

Expected:

```text
js ok
```

## Acceptance Criteria

- [ ] `Prepare Telegram Payload` JavaScript parses successfully.
- [ ] `n8n_node.json` is valid JSON.
- [ ] `video_path` is absolute when `files[].path` is relative.
- [ ] `Read Binary File` reads `={{ $json.video_path }}`.
- [ ] Workflow does not hardcode `short_01_wm.mp4`.
- [ ] Telegram video still uses dynamic watermarked file from `files[]`.
- [ ] Telegram metadata text still sends from `Prepare Telegram Payload -> Send a text message`.

## Note

This fix assumes n8n can read this local folder:

```text
/Users/agusrachman/Documents/Codex/content-short/storage
```

If n8n runs inside Docker without this folder mounted, use `watermarkedVideo.download_url` with an HTTP Request binary download instead of `Read Binary File`.
