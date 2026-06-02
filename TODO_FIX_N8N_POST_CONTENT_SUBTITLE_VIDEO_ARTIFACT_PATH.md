# TODO: Fix N8N Post Content Subtitle Video Artifact Path

## Status

OPEN

## Goal

Fix `n8n_post_content.json` so the subtitle step sends the correct video artifact to `/subtitle/burn`.

Current workflow sends this hardcoded file:

```text
/Users/agusrachman/Documents/Codex/content-short/storage/free-viral-shorts/{{ video_id }}/shorts/short_01.mp4
```

That is unsafe because:

- it always uses `short_01.mp4`
- it ignores `render_payload.clip_index`
- it runs after the opening step but still uses the pre-opening `shorts` artifact
- the current failing file has no audio stream, so `auto-captions` cannot extract `audio.wav`

The fix must make the subtitle node use a deterministic artifact path that matches the clip being processed and is likely to contain audio.

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

## Current Failure

Subtitle job failed with:

```text
[PackageEngine] Auto-captions FAILED: Package execution failed: auto-captions
Command: ... caption_generator.py -i .../storage/free-viral-shorts/5G2Vs3cVUrM/shorts/short_01.mp4 -a .../audio.wav -o .../word_timestamps.json ...
Return code: 1
```

Investigation showed:

```text
storage/free-viral-shorts/5G2Vs3cVUrM/shorts/short_01.mp4
```

has only video stream and no audio stream.

`auto-captions` needs audio. If the input video has no audio stream, `caption_generator.py` cannot create:

```text
audio.wav
word_timestamps.json
```

## Problem Node

Node name:

```text
Trigger Subtitle Generator1
```

Current parameter:

```json
{
  "name": "video_path",
  "value": "=/Users/agusrachman/Documents/Codex/content-short/storage/free-viral-shorts/{{ $('Code in JavaScript1').first().json.video_id }}/shorts/short_01.mp4"
}
```

This is the main bug.

## Required Behavior

The subtitle step must not hardcode `short_01.mp4`.

It must use `render_payload.clip_index` to build the clip filename:

```text
short_01.mp4
short_02.mp4
short_03.mp4
...
```

For this workflow, prefer the opening artifact if it exists because the workflow order is:

```text
render -> opening -> subtitle -> watermark -> send Telegram
```

The preferred subtitle input should be:

```text
/Users/agusrachman/Documents/Codex/content-short/storage/free-viral-shorts/{{ video_id }}/opening/short_XX_with_opening.mp4
```

Fallback path should be:

```text
/Users/agusrachman/Documents/Codex/content-short/storage/free-viral-shorts/{{ video_id }}/shorts/short_XX.mp4
```

Important:

- `XX` must be zero-padded to 2 digits.
- `clip_index = 1` means `short_01`.
- `clip_index = 2` means `short_02`.
- The path must be generated in a Code node before `Trigger Subtitle Generator1`.

## Implementation Plan

### Step 1: Add Code Node Before Subtitle Trigger

Add a Code node named exactly:

```text
Prepare Subtitle Video Path
```

Place it between:

```text
If Opening Completed1
```

and:

```text
Trigger Subtitle Generator1
```

The true branch of `If Opening Completed1` must go to `Prepare Subtitle Video Path`.

Then `Prepare Subtitle Video Path` must go to `Trigger Subtitle Generator1`.

### Step 2: Code For `Prepare Subtitle Video Path`

Use this exact JavaScript:

```js
const original = $('Code in JavaScript1').first().json;
const current = $input.first().json;

const videoId = original.video_id;
if (!videoId) {
  throw new Error('video_id tidak ditemukan dari payload utama');
}

const clipIndex = Number(original.render_payload?.clip_index || 1);
if (!Number.isInteger(clipIndex) || clipIndex < 1) {
  throw new Error(`render_payload.clip_index tidak valid: ${original.render_payload?.clip_index}`);
}

const clipNumber = String(clipIndex).padStart(2, '0');
const baseDir = `/Users/agusrachman/Documents/Codex/content-short/storage/free-viral-shorts/${videoId}`;

return [
  {
    json: {
      ...current,
      video_id: current.video_id || videoId,
      subtitle_video_path: `${baseDir}/opening/short_${clipNumber}_with_opening.mp4`,
      subtitle_fallback_video_path: `${baseDir}/shorts/short_${clipNumber}.mp4`,
      clip_index: clipIndex,
      clip_number: clipNumber
    }
  }
];
```

This node does not check the filesystem because n8n Code nodes may run in a different runtime context. It only prepares deterministic paths.

### Step 3: Update `Trigger Subtitle Generator1`

In node:

```text
Trigger Subtitle Generator1
```

Change the `video_path` body parameter from hardcoded `short_01.mp4` to:

```text
={{ $json.subtitle_video_path }}
```

Do not change the other body parameters:

```text
language = id
engine = auto-captions
style = viral_clip_pro
replace_original = true
transcribe_model = medium
transcribe_preset = accurate
audio_preset = speech
```

### Step 4: Preserve Job Context In Remap Subtitle Node

In node:

```text
Remap Subtitle Job ID1
```

Keep reading the subtitle API response from `Trigger Subtitle Generator1`, but also preserve the prepared video path from `Prepare Subtitle Video Path`.

Replace the current JavaScript with:

```js
const items = $('Trigger Subtitle Generator1').all();
const prepared = $('Prepare Subtitle Video Path').first().json;

return items.map(item => {
  const body = item.json.body || item.json;

  if (!body.job_id) {
    throw new Error(`Subtitle job_id tidak ditemukan. Response: ${JSON.stringify(item.json)}`);
  }

  return {
    json: {
      job_id: body.job_id,
      step: 'subtitle',
      status_url: body.status_url || `/subtitle/jobs/${body.job_id}`,
      result_url: body.result_url || `/subtitle/jobs/${body.job_id}`,
      source: $('Code in JavaScript1').first().json.source,
      video_id: $('Code in JavaScript1').first().json.video_id,
      subtitle_video_path: prepared.subtitle_video_path,
      subtitle_fallback_video_path: prepared.subtitle_fallback_video_path,
      clip_index: prepared.clip_index,
      clip_number: prepared.clip_number
    }
  };
});
```

### Step 5: Fix Notification Bridge If Needed

If the current flow is:

```text
Trigger Subtitle Generator1
-> Notif Subtitle
-> Remap Subtitle Job ID1
```

keep it working, but avoid using Telegram output as the source of `job_id`.

The replacement code in Step 4 already handles this by reading:

```js
$('Trigger Subtitle Generator1').all()
```

So this step is optional.

Do not rewire all notification nodes in this issue. Keep this issue focused on subtitle video artifact path.

## Important Limitation

This n8n-only fix assumes the opening output exists and is valid:

```text
opening/short_XX_with_opening.mp4
```

If the opening artifact is `0B` or invalid, subtitle will still fail.

That is a separate backend/opening-render issue, not part of this n8n issue.

However, this fix is still needed because the current n8n workflow definitely points subtitle to the wrong hardcoded file.

## Validation Commands

Run this command to validate JSON:

```bash
python3 -m json.tool n8n_post_content.json > /tmp/n8n_post_content.validated.json
```

Run this command to ensure the bad hardcoded subtitle path is gone:

```bash
python3 - <<'PY'
import json

data = json.load(open('n8n_post_content.json'))
node = next(n for n in data['nodes'] if n['name'] == 'Trigger Subtitle Generator1')

params = node['parameters']['bodyParameters']['parameters']
video_path = next(p['value'] for p in params if p['name'] == 'video_path')

if 'short_01.mp4' in video_path:
    raise SystemExit(f'BAD: video_path still hardcodes short_01.mp4: {video_path}')

if video_path != '={{ $json.subtitle_video_path }}':
    raise SystemExit(f'BAD: video_path must use subtitle_video_path, got: {video_path}')

print('OK: subtitle video_path uses prepared subtitle_video_path')
PY
```

Run this command to ensure the new Code node exists:

```bash
python3 - <<'PY'
import json

data = json.load(open('n8n_post_content.json'))
names = {node['name'] for node in data['nodes']}

required = {
    'Prepare Subtitle Video Path',
    'Trigger Subtitle Generator1',
    'Remap Subtitle Job ID1',
}

missing = required - names
if missing:
    raise SystemExit(f'Missing required nodes: {sorted(missing)}')

print('OK: required subtitle path nodes exist')
PY
```

Run this command to check the required connections:

```bash
python3 - <<'PY'
import json

data = json.load(open('n8n_post_content.json'))
connections = data.get('connections', {})

def targets(source):
    result = []
    for group in connections.get(source, {}).get('main', []):
        result.extend(edge['node'] for edge in group)
    return result

if 'Prepare Subtitle Video Path' not in targets('If Opening Completed1'):
    raise SystemExit('If Opening Completed1 true branch must connect to Prepare Subtitle Video Path')

if 'Trigger Subtitle Generator1' not in targets('Prepare Subtitle Video Path'):
    raise SystemExit('Prepare Subtitle Video Path must connect to Trigger Subtitle Generator1')

print('OK: subtitle path preparation is wired before subtitle trigger')
PY
```

## Manual Validation

After importing the fixed workflow into n8n:

1. Send a payload with `render_payload.clip_index = 1`.
2. Confirm `Prepare Subtitle Video Path` outputs:

```text
subtitle_video_path = .../opening/short_01_with_opening.mp4
subtitle_fallback_video_path = .../shorts/short_01.mp4
```

3. Send a payload with `render_payload.clip_index = 2`.
4. Confirm it outputs:

```text
subtitle_video_path = .../opening/short_02_with_opening.mp4
subtitle_fallback_video_path = .../shorts/short_02.mp4
```

5. Run subtitle step only after opening step completed.
6. Confirm `/subtitle/burn` receives `video_path` from `$json.subtitle_video_path`.

## Acceptance Criteria

- `n8n_post_content.json` is valid JSON.
- Node `Prepare Subtitle Video Path` exists.
- `If Opening Completed1` true branch connects to `Prepare Subtitle Video Path`.
- `Prepare Subtitle Video Path` connects to `Trigger Subtitle Generator1`.
- `Trigger Subtitle Generator1` no longer hardcodes `short_01.mp4`.
- `Trigger Subtitle Generator1` uses:

```text
={{ $json.subtitle_video_path }}
```

- The generated path uses `render_payload.clip_index`.
- `clip_index = 1` maps to `short_01`.
- `clip_index = 2` maps to `short_02`.
- `Remap Subtitle Job ID1` preserves `subtitle_video_path`, `subtitle_fallback_video_path`, `clip_index`, and `clip_number`.
- No changes are made to backend Python or shell scripts in this issue.

