# TODO: Fix N8N Post Content Notification Wiring Preserve Payload

## Status

OPEN

## Goal

Fix `n8n_post_content.json` so Telegram process notifications do not break the main workflow payload.

Current implementation added notification nodes, but some Telegram notification nodes are used as serial bridge nodes. This is wrong because Telegram nodes output Telegram API response data, not the original job/status payload.

The workflow must:

- keep sending process notifications to Telegram
- keep final YouTube metadata delivery working
- keep final watermarked video delivery working
- never send every polling loop notification
- preserve the original payload for the next processing node

## File To Edit

Edit only:

```text
n8n_post_content.json
```

Do not edit:

```text
api_server.py
prompt.md
n8n_node.json
TODO_IMPROVE_N8N_POST_CONTENT_TELEGRAM_PROCESS_NOTIFICATIONS.md
```

## Problem Summary

Telegram notification nodes are currently placed like this:

```text
HTTP Request5
-> Build Notify Render Started
-> Notify Render Started
-> Remap Render Job ID
```

This is broken.

After `Notify Render Started`, the item JSON is Telegram response data. `Remap Render Job ID` expects the render API response with `job_id`, so it can fail with:

```text
Render job_id tidak ditemukan
```

The same mistake exists in other steps.

## Correct Pattern

Use notification nodes as side effects.

Correct pattern:

```text
Previous Node
-> Build Notify X
   -> Notify X
   -> Next Main Workflow Node
```

Important:

- `Notify X` must not connect to the next main workflow node.
- `Build Notify X` may connect to both `Notify X` and the next main workflow node.
- The next main workflow node must receive the original payload preserved by `Build Notify X`.

This works because each `Build Notify X` node returns:

```js
{
  json: {
    ...current,
    chat_id,
    video_id,
    notification_text
  }
}
```

So the original fields like `job_id`, `status`, `video_download_url`, `metadata_text`, and `caption` are preserved.

## Plan

1. Validate `n8n_post_content.json` parses as JSON.
2. Fix render-start wiring so `Remap Render Job ID` receives output from `Build Notify Render Started`, not `Notify Render Started`.
3. Fix render-completed wiring so `Trigger Opening Narration` receives output from `Build Notify Render Completed`, not `Notify Render Completed`.
4. Fix opening-start wiring so `Cek Status Opening` receives output from `Build Notify Opening Started`, not `Notify Opening Started`.
5. Fix opening-completed wiring so `Trigger Subtitle Generator` receives output from `Build Notify Opening Completed`, not `Notify Opening Completed`.
6. Fix subtitle-start wiring so `Cek Status Subtitle` receives output from `Build Notify Subtitle Started`, not `Notify Subtitle Started`.
7. Fix subtitle-completed wiring so `Trigger Watermark` receives output from `Build Notify Subtitle Completed`, not `Notify Subtitle Completed`.
8. Fix watermark-start wiring so `Cek Status Watermark` receives output from `Build Notify Watermark Started`, not `Notify Watermark Started`.
9. Fix watermark-completed wiring so `Get Watermark Result1` receives output from `Build Notify Watermark Completed`, not `Notify Watermark Completed`.
10. Fix delivery-start wiring so `Send a text message1` and `Download Watermark Video1` receive output from `Build Notify Delivery Started`, not `Notify Delivery Started`.
11. Keep failed notification branches stopping at their Telegram notification node.
12. Validate JSON, node names, and required connections.

## Exact Connection Fixes

### 1. Render Started

Current broken flow:

```text
HTTP Request5
-> Build Notify Render Started
-> Notify Render Started
-> Remap Render Job ID
```

Change to:

```text
HTTP Request5
-> Build Notify Render Started

Build Notify Render Started
-> Notify Render Started
-> Remap Render Job ID
```

After this fix:

```json
"Build Notify Render Started": {
  "main": [
    [
      {
        "node": "Notify Render Started",
        "type": "main",
        "index": 0
      },
      {
        "node": "Remap Render Job ID",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

And:

```json
"Notify Render Started": {
  "main": [
    []
  ]
}
```

If n8n export omits empty connections, it is also okay to remove `"Notify Render Started"` from `connections`.

### 2. Render Completed

Current broken flow:

```text
Build Notify Render Completed
-> Notify Render Completed
-> Trigger Opening Narration
```

Change to:

```text
Build Notify Render Completed
-> Notify Render Completed
-> Trigger Opening Narration
```

Meaning `Trigger Opening Narration` must be connected directly from `Build Notify Render Completed`, not from `Notify Render Completed`.

Expected connection:

```json
"Build Notify Render Completed": {
  "main": [
    [
      {
        "node": "Notify Render Completed",
        "type": "main",
        "index": 0
      },
      {
        "node": "Trigger Opening Narration",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Remove the outgoing connection from `Notify Render Completed`.

### 3. Opening Started

Expected connection:

```json
"Build Notify Opening Started": {
  "main": [
    [
      {
        "node": "Notify Opening Started",
        "type": "main",
        "index": 0
      },
      {
        "node": "Cek Status Opening",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Remove the outgoing connection from `Notify Opening Started`.

### 4. Opening Completed

Expected connection:

```json
"Build Notify Opening Completed": {
  "main": [
    [
      {
        "node": "Notify Opening Completed",
        "type": "main",
        "index": 0
      },
      {
        "node": "Trigger Subtitle Generator",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Remove the outgoing connection from `Notify Opening Completed`.

### 5. Subtitle Started

Expected connection:

```json
"Build Notify Subtitle Started": {
  "main": [
    [
      {
        "node": "Notify Subtitle Started",
        "type": "main",
        "index": 0
      },
      {
        "node": "Cek Status Subtitle",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Remove the outgoing connection from `Notify Subtitle Started`.

### 6. Subtitle Completed

Expected connection:

```json
"Build Notify Subtitle Completed": {
  "main": [
    [
      {
        "node": "Notify Subtitle Completed",
        "type": "main",
        "index": 0
      },
      {
        "node": "Trigger Watermark",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Remove the outgoing connection from `Notify Subtitle Completed`.

### 7. Watermark Started

Expected connection:

```json
"Build Notify Watermark Started": {
  "main": [
    [
      {
        "node": "Notify Watermark Started",
        "type": "main",
        "index": 0
      },
      {
        "node": "Cek Status Watermark",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Remove the outgoing connection from `Notify Watermark Started`.

### 8. Watermark Completed

Expected connection:

```json
"Build Notify Watermark Completed": {
  "main": [
    [
      {
        "node": "Notify Watermark Completed",
        "type": "main",
        "index": 0
      },
      {
        "node": "Get Watermark Result1",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Remove the outgoing connection from `Notify Watermark Completed`.

### 9. Delivery Started

Current broken flow:

```text
Build Notify Delivery Started
-> Notify Delivery Started
-> Send a text message1
-> Download Watermark Video1
```

This is broken because `Send a text message1` needs:

```text
$json.metadata_text
```

and `Download Watermark Video1` needs:

```text
$json.video_download_url
```

Those fields exist in the output of `Build Notify Delivery Started`, not in the Telegram output from `Notify Delivery Started`.

Expected connection:

```json
"Build Notify Delivery Started": {
  "main": [
    [
      {
        "node": "Notify Delivery Started",
        "type": "main",
        "index": 0
      },
      {
        "node": "Send a text message1",
        "type": "main",
        "index": 0
      },
      {
        "node": "Download Watermark Video1",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Remove the outgoing connection from `Notify Delivery Started`.

## Failed Branches

Failed notification branches may stop after Telegram notification.

These are okay:

```text
If Render Failed true
-> Build Notify Render Failed
-> Notify Render Failed
```

```text
If Opening Failed true
-> Build Notify Opening Failed
-> Notify Opening Failed
```

```text
If Subtitle Failed true
-> Build Notify Subtitle Failed
-> Notify Subtitle Failed
```

```text
If Watermark Failed true
-> Build Notify Watermark Failed
-> Notify Watermark Failed
```

Do not connect failed notification nodes back to the main workflow.

## Optional Context Improvement

If easy, add `original_payload` to these keep-context nodes:

```text
Keep Opening Status Context
Keep Subtitle Status Context
Keep Watermark Status Context
```

Example:

```js
original_payload: ctx.original_payload || $('Code in JavaScript').first().json
```

This is optional because current notification builders use:

```js
$('Code in JavaScript').first().json
```

But adding `original_payload` makes the workflow more robust.

## Validation Commands

Run this command to validate JSON:

```bash
python3 -m json.tool n8n_post_content.json > /tmp/n8n_post_content.validated.json
```

Run this command to check duplicate node names and broken connections:

```bash
python3 - <<'PY'
import json
from collections import Counter

path = 'n8n_post_content.json'
data = json.load(open(path))
names = [node['name'] for node in data['nodes']]

duplicates = [name for name, count in Counter(names).items() if count > 1]
if duplicates:
    raise SystemExit(f'Duplicate node names: {duplicates}')

missing = []
for source, config in data.get('connections', {}).items():
    if source not in names:
        missing.append(f'Missing source node: {source}')
    for output_group in config.get('main', []):
        for edge in output_group:
            if edge['node'] not in names:
                missing.append(f"Missing target node: {source} -> {edge['node']}")

if missing:
    raise SystemExit('\n'.join(missing))

print('OK: no duplicate names and no broken connections')
PY
```

Run this command to ensure notification Telegram nodes are not serial bridges:

```bash
python3 - <<'PY'
import json

data = json.load(open('n8n_post_content.json'))
connections = data.get('connections', {})

notify_nodes_that_must_not_continue_main_flow = [
    'Notify Render Started',
    'Notify Render Completed',
    'Notify Opening Started',
    'Notify Opening Completed',
    'Notify Subtitle Started',
    'Notify Subtitle Completed',
    'Notify Watermark Started',
    'Notify Watermark Completed',
    'Notify Delivery Started',
]

bad = []
for name in notify_nodes_that_must_not_continue_main_flow:
    edges = []
    for group in connections.get(name, {}).get('main', []):
        edges.extend(group)
    if edges:
        bad.append((name, [edge['node'] for edge in edges]))

if bad:
    raise SystemExit(f'These Notify nodes still continue the main flow: {bad}')

print('OK: Notify nodes are not serial bridge nodes')
PY
```

Run this command to ensure builder nodes continue the main workflow:

```bash
python3 - <<'PY'
import json

data = json.load(open('n8n_post_content.json'))
connections = data.get('connections', {})

required = {
    'Build Notify Render Started': ['Notify Render Started', 'Remap Render Job ID'],
    'Build Notify Render Completed': ['Notify Render Completed', 'Trigger Opening Narration'],
    'Build Notify Opening Started': ['Notify Opening Started', 'Cek Status Opening'],
    'Build Notify Opening Completed': ['Notify Opening Completed', 'Trigger Subtitle Generator'],
    'Build Notify Subtitle Started': ['Notify Subtitle Started', 'Cek Status Subtitle'],
    'Build Notify Subtitle Completed': ['Notify Subtitle Completed', 'Trigger Watermark'],
    'Build Notify Watermark Started': ['Notify Watermark Started', 'Cek Status Watermark'],
    'Build Notify Watermark Completed': ['Notify Watermark Completed', 'Get Watermark Result1'],
    'Build Notify Delivery Started': ['Notify Delivery Started', 'Send a text message1', 'Download Watermark Video1'],
}

missing = []
for source, targets in required.items():
    actual = []
    for group in connections.get(source, {}).get('main', []):
        actual.extend(edge['node'] for edge in group)
    for target in targets:
        if target not in actual:
            missing.append(f'{source} must connect to {target}; actual={actual}')

if missing:
    raise SystemExit('\n'.join(missing))

print('OK: builder nodes continue notification and main workflow')
PY
```

## Acceptance Criteria

- `n8n_post_content.json` is valid JSON.
- No duplicate node names.
- No broken connection targets.
- `Notify Render Started` does not connect to `Remap Render Job ID`.
- `Notify Render Completed` does not connect to `Trigger Opening Narration`.
- `Notify Opening Started` does not connect to `Cek Status Opening`.
- `Notify Opening Completed` does not connect to `Trigger Subtitle Generator`.
- `Notify Subtitle Started` does not connect to `Cek Status Subtitle`.
- `Notify Subtitle Completed` does not connect to `Trigger Watermark`.
- `Notify Watermark Started` does not connect to `Cek Status Watermark`.
- `Notify Watermark Completed` does not connect to `Get Watermark Result1`.
- `Notify Delivery Started` does not connect to `Send a text message1`.
- `Notify Delivery Started` does not connect to `Download Watermark Video1`.
- `Build Notify Delivery Started` connects directly to `Send a text message1`.
- `Build Notify Delivery Started` connects directly to `Download Watermark Video1`.
- Final `Send a text message1` still receives `metadata_text`.
- Final `Download Watermark Video1` still receives `video_download_url`.
- Final `Send a video1` still receives downloaded binary data.
- Failed notification branches stop after their Telegram notification node.

## Quick Manual Test In N8N

After importing the fixed workflow:

1. Send one valid payload to `Telegram Trigger3`.
2. Confirm Telegram receives `Render dimulai`.
3. Confirm workflow does not fail at `Remap Render Job ID`.
4. Confirm completed notifications arrive once per step.
5. Confirm final YouTube metadata message is sent.
6. Confirm final watermarked video is sent.
7. Confirm final `Semua proses selesai` notification is sent after `Send a video1`.

