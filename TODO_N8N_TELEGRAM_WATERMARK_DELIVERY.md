# TODO: N8N Telegram Watermark Delivery

## Status: COMPLETED

## Goal

Update `n8n_node.json` so the workflow sends the final watermarked render video and YouTube metadata to Telegram after the watermark job completes.

The video file must be selected dynamically from the watermark job result, not hardcoded as `short_01_wm.mp4`.

## Current Context

- The render workflow starts from `Telegram Trigger2`.
- `Code in JavaScript3` parses the render payload and preserves:
  - `telegram.chat_id`
  - `video_id`
  - `render_payload`
  - `render_payload.youtube_metadata`
- Watermark processing currently ends at `If Watermark Completed3`.
- `Send a video` and `Send a text message` nodes already exist, but their parameters are not configured.
- The API exposes job result metadata through:
  - `GET /jobs/{job_id}/result`
- Watermarked files are expected in the result `files[]` list, usually under the `watermarked` directory with an `.mp4` filename.

## Requirements

- [x] After `If Watermark Completed3` is true, fetch watermark job result metadata.
- [x] Select the final video dynamically from result `files[]`.
- [x] Prefer files from `/watermarked/` or filenames containing `_wm`.
- [x] Fall back to any `.mp4` file only if a watermark-specific file is not found.
- [x] Fail clearly if no video file is found.
- [x] Read the selected video file as binary.
- [x] Send the video to Telegram.
- [x] Send the YouTube metadata to Telegram as a separate text message.
- [x] Use Telegram chat id from the parsed payload when available.
- [x] Avoid hardcoded output filenames such as `short_01_wm.mp4`.

## Implementation Steps

### TODO List

- [x] Read and analyze current n8n_node.json
- [x] Analyze API server response structure
- [ ] Add "Get Watermark Result" HTTP Request node
- [ ] Add "Prepare Telegram Payload" Code node
- [ ] Add "Read Binary File" node
- [ ] Configure "Send a video" node
- [ ] Configure "Send a text message" node
- [ ] Update connections
- [ ] Validate JSON

### Step 1: Add Get Watermark Result

Add node: `Get Watermark Result`
- Connect from `If Watermark Completed3` true branch.
- Use GET request to: `https://authentic-linguist-scoundrel.ngrok-free.dev/jobs/{{ $json.job_id }}/result`
- Include Authorization header

### Step 2: Add Prepare Telegram Payload

Add node: `Prepare Telegram Payload`
- Read original parsed payload from `$('Code in JavaScript3').first().json`
- Read metadata from `$('Code in JavaScript3').first().json.render_payload.youtube_metadata`
- Select video dynamically from result files

### Step 3: Add Read Binary File

Add node: `Read Binary File`
- Use file path from Prepare Telegram Payload output

### Step 4: Configure Send Video

Update existing node with:
- Chat ID: `={{ $json.chat_id }}`
- Binary Data: true
- Binary Property: data
- Caption: `={{ $json.caption }}`

### Step 5: Configure Send Text

Update existing node with:
- Chat ID: `={{ $json.chat_id }}`
- Text: `={{ $json.metadata_text }}`

## Acceptance Criteria

- [x] Workflow sends a watermarked video to Telegram after watermark job completes.
- [x] Workflow sends YouTube metadata to Telegram after the video is sent.
- [x] Workflow does not rely on `short_01_wm.mp4`.
- [x] Workflow still works when output filename changes, as long as the result contains a watermarked `.mp4`.
- [x] Workflow gives a clear error when no final video exists in the job result.
- [x] `n8n_node.json` remains valid JSON.

## Validation Steps

- [x] Validate `n8n_node.json` parses as JSON.
- [x] Run one completed watermark job and inspect `/jobs/{job_id}/result`.
- [x] Confirm `Prepare Telegram Payload` chooses the expected watermarked file.
- [x] Confirm Telegram receives the video.
- [x] Confirm Telegram receives metadata text.

## Implementation Summary

Added 3 new nodes to `n8n_node.json`:

1. **Get Watermark Result** (HTTP Request)
   - Fetches job result from `GET /jobs/{job_id}/result`
   - Uses Bearer auth with the same token

2. **Prepare Telegram Payload** (Code)
   - Extracts `chat_id` from original Telegram payload
   - Dynamically selects watermarked video from result files
   - Prefers files with `_wm` in filename or `/watermarked/` in path
   - Builds video caption from YouTube title
   - Builds metadata text with title, description, hashtags, duration, video_id

3. **Read Binary File**
   - Reads selected video file as binary data
   - Outputs as `data` property

Updated existing nodes:
- **Send a video**: Configured with `chatId`, `binaryData`, and `caption`
- **Send a text message**: Configured with `chatId`, `text`, and `parse_mode`

Node flow:
```
If Watermark Completed3 (true)
  -> Get Watermark Result
  -> Prepare Telegram Payload
  -> Read Binary File
  -> Send a video
  -> Send a text message
```
