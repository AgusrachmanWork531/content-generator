# TODO: Improve N8N Post Content Telegram Process Notifications

## Status

COMPLETED

## Goal

Improve `n8n_post_content.json` so the user receives Telegram notifications during the process, not only at the final delivery.

The workflow must notify Telegram when each major step:

- starts
- completes
- fails

Major steps:

```text
render
opening
subtitle
watermark
delivery
```

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
render payload validation code
final Send a video1 behavior
final Send a text message1 behavior
```

## Current Workflow Summary

Current main flow:

```text
Telegram Trigger3
-> Code in JavaScript
-> HTTP Request5
-> Remap Render Job ID
-> HTTP Request
-> Keep Render Status Context
-> If
-> Trigger Opening Narration
-> Remap Opening Job ID
-> Cek Status Opening
-> Keep Opening Status Context
-> If Opening Completed
-> Trigger Subtitle Generator
-> Remap Subtitle Job ID
-> Cek Status Subtitle
-> Keep Subtitle Status Context
-> If Subtitle Completed
-> Trigger Watermark
-> Remap Watermark Job ID
-> Cek Status Watermark
-> Keep Watermark Status Context
-> If Watermark Completed
-> Get Watermark Result1
-> Prepare Telegram Payload1
-> Send a text message1
-> Download Watermark Video1
-> Send a video1
```

Existing final delivery nodes must keep working:

```text
Send a text message1
Download Watermark Video1
Send a video1
```

## Important Rule

Do not send a Telegram message on every polling loop.

Only send notifications on:

```text
step started
step completed
step failed
delivery started
delivery completed
```

This prevents Telegram spam.

## Notification Message Format

Use short Indonesian messages.

### Started

```text
🚀 Render dimulai

Video ID: {{video_id}}
Judul: {{title}}
Job ID: {{job_id}}
Status: {{status}}
```

### Completed

```text
✅ Render selesai

Video ID: {{video_id}}
Judul: {{title}}
Job ID: {{job_id}}
```

### Failed

```text
❌ Render gagal

Video ID: {{video_id}}
Judul: {{title}}
Job ID: {{job_id}}

Error:
{{error}}
```

### Delivery started

```text
📤 Mengirim hasil ke Telegram

Video ID: {{video_id}}
File: {{filename}}
```

### Delivery completed

```text
✅ Semua proses selesai

Video watermark dan metadata YouTube sudah dikirim.
```

## Shared Telegram Node Settings

Every process notification Telegram node must use:

```json
{
  "chatId": "={{ $json.chat_id }}",
  "text": "={{ $json.notification_text }}",
  "additionalFields": {
    "parse_mode": "Markdown"
  }
}
```

Use the same Telegram credential as existing Telegram nodes:

```json
{
  "telegramApi": {
    "id": "wo2KtQA3GKUjikub",
    "name": "Telegram account"
  }
}
```

## Step 1: Add Notification Builder Code Nodes

Add one Code node per notification. This is easier for cheap models than making one reusable complex node.

Use these node names exactly:

```text
Build Notify Render Started
Build Notify Render Completed
Build Notify Render Failed
Build Notify Opening Started
Build Notify Opening Completed
Build Notify Opening Failed
Build Notify Subtitle Started
Build Notify Subtitle Completed
Build Notify Subtitle Failed
Build Notify Watermark Started
Build Notify Watermark Completed
Build Notify Watermark Failed
Build Notify Delivery Started
Build Notify Delivery Completed
```

Each builder must return one item:

```js
const original = $('Code in JavaScript').first().json;
const current = $input.first().json;
const yt = original.render_payload?.youtube_metadata || {};

const chat_id = original.telegram?.chat_id;
if (!chat_id) {
  throw new Error('chat_id tidak ditemukan untuk notifikasi Telegram');
}

return [
  {
    json: {
      ...current,
      chat_id,
      video_id: current.video_id || original.video_id || '-',
      notification_text: [
        '🚀 Render dimulai',
        '',
        `Video ID: ${current.video_id || original.video_id || '-'}`,
        `Judul: ${yt.title || '-'}`,
        `Job ID: ${current.job_id || '-'}`,
        `Status: ${current.status || 'queued'}`
      ].join('\n')
    }
  }
];
```

Change the first line text for each builder:

```text
🚀 Render dimulai
✅ Render selesai
❌ Render gagal
🚀 Opening dimulai
✅ Opening selesai
❌ Opening gagal
🚀 Subtitle dimulai
✅ Subtitle selesai
❌ Subtitle gagal
🚀 Watermark dimulai
✅ Watermark selesai
❌ Watermark gagal
📤 Mengirim hasil ke Telegram
✅ Semua proses selesai
```

For failed builders, include error:

```js
`Error:\n${current.error || 'Unknown error'}`
```

For delivery started, use:

```js
`File: ${current.filename || '-'}`
```

For delivery completed, use simple text:

```js
notification_text: [
  '✅ Semua proses selesai',
  '',
  'Video watermark dan metadata YouTube sudah dikirim.'
].join('\n')
```

## Step 2: Add Notification Telegram Nodes

Add these Telegram nodes:

```text
Notify Render Started
Notify Render Completed
Notify Render Failed
Notify Opening Started
Notify Opening Completed
Notify Opening Failed
Notify Subtitle Started
Notify Subtitle Completed
Notify Subtitle Failed
Notify Watermark Started
Notify Watermark Completed
Notify Watermark Failed
Notify Delivery Started
Notify Delivery Completed
```

Each Telegram node must use:

```text
chatId: ={{ $json.chat_id }}
text: ={{ $json.notification_text }}
parse_mode: Markdown
```

## Step 3: Add Failed IF Nodes

Current completed IF nodes only check:

```text
status == completed
```

Add failed IF nodes before each completed IF:

```text
If Render Failed
If Opening Failed
If Subtitle Failed
If Watermark Failed
```

Each failed IF condition:

```text
status == failed
```

Important:

- `true` branch sends failed notification and stops.
- `false` branch goes to the existing completed IF.
- `queued` and `running` must continue to existing wait loop.

## Step 4: Update Render Flow

Current:

```text
HTTP Request5 -> Remap Render Job ID -> HTTP Request
HTTP Request -> Keep Render Status Context -> If
If true -> Trigger Opening Narration
If false -> Wait -> HTTP Request
```

Change to:

```text
HTTP Request5
-> Remap Render Job ID
-> Build Notify Render Started
-> Notify Render Started
-> HTTP Request

HTTP Request
-> Keep Render Status Context
-> If Render Failed

If Render Failed true
-> Build Notify Render Failed
-> Notify Render Failed

If Render Failed false
-> If

If true
-> Build Notify Render Completed
-> Notify Render Completed
-> Trigger Opening Narration

If false
-> Wait
-> HTTP Request
```

Do not rename existing node `If`.

## Step 5: Update Opening Flow

Current:

```text
Trigger Opening Narration -> Remap Opening Job ID -> Cek Status Opening
Cek Status Opening -> Keep Opening Status Context -> If Opening Completed
If Opening Completed true -> Trigger Subtitle Generator
If Opening Completed false -> Wait Opening -> Cek Status Opening
```

Change to:

```text
Trigger Opening Narration
-> Remap Opening Job ID
-> Build Notify Opening Started
-> Notify Opening Started
-> Cek Status Opening

Cek Status Opening
-> Keep Opening Status Context
-> If Opening Failed

If Opening Failed true
-> Build Notify Opening Failed
-> Notify Opening Failed

If Opening Failed false
-> If Opening Completed

If Opening Completed true
-> Build Notify Opening Completed
-> Notify Opening Completed
-> Trigger Subtitle Generator

If Opening Completed false
-> Wait Opening
-> Cek Status Opening
```

## Step 6: Update Subtitle Flow

Current:

```text
Trigger Subtitle Generator -> Remap Subtitle Job ID -> Cek Status Subtitle
Cek Status Subtitle -> Keep Subtitle Status Context -> If Subtitle Completed
If Subtitle Completed true -> Trigger Watermark
If Subtitle Completed false -> Wait Subtitle -> Cek Status Subtitle
```

Change to:

```text
Trigger Subtitle Generator
-> Remap Subtitle Job ID
-> Build Notify Subtitle Started
-> Notify Subtitle Started
-> Cek Status Subtitle

Cek Status Subtitle
-> Keep Subtitle Status Context
-> If Subtitle Failed

If Subtitle Failed true
-> Build Notify Subtitle Failed
-> Notify Subtitle Failed

If Subtitle Failed false
-> If Subtitle Completed

If Subtitle Completed true
-> Build Notify Subtitle Completed
-> Notify Subtitle Completed
-> Trigger Watermark

If Subtitle Completed false
-> Wait Subtitle
-> Cek Status Subtitle
```

## Step 7: Update Watermark Flow

Current:

```text
Trigger Watermark -> Remap Watermark Job ID -> Cek Status Watermark
Cek Status Watermark -> Keep Watermark Status Context -> If Watermark Completed
If Watermark Completed true -> Get Watermark Result1
If Watermark Completed false -> Wait Watermark -> Cek Status Watermark
```

Change to:

```text
Trigger Watermark
-> Remap Watermark Job ID
-> Build Notify Watermark Started
-> Notify Watermark Started
-> Cek Status Watermark

Cek Status Watermark
-> Keep Watermark Status Context
-> If Watermark Failed

If Watermark Failed true
-> Build Notify Watermark Failed
-> Notify Watermark Failed

If Watermark Failed false
-> If Watermark Completed

If Watermark Completed true
-> Build Notify Watermark Completed
-> Notify Watermark Completed
-> Get Watermark Result1

If Watermark Completed false
-> Wait Watermark
-> Cek Status Watermark
```

## Step 8: Update Delivery Flow

Current:

```text
Get Watermark Result1
-> Prepare Telegram Payload1
-> Send a text message1
-> Download Watermark Video1
-> Send a video1
```

Change to:

```text
Get Watermark Result1
-> Prepare Telegram Payload1
-> Build Notify Delivery Started
-> Notify Delivery Started
```

After `Notify Delivery Started`, split to existing final delivery:

```text
Notify Delivery Started
-> Send a text message1
Notify Delivery Started
-> Download Watermark Video1
```

Keep:

```text
Download Watermark Video1 -> Send a video1
```

Add:

```text
Send a video1
-> Build Notify Delivery Completed
-> Notify Delivery Completed
```

## Step 9: Preserve Context In Keep Nodes

Make sure these nodes keep `source`, `video_id`, and ideally `original_payload`:

```text
Keep Render Status Context
Keep Opening Status Context
Keep Subtitle Status Context
Keep Watermark Status Context
```

If a keep node does not preserve `original_payload`, add:

```js
original_payload: ctx.original_payload || $('Code in JavaScript').first().json
```

Do not remove existing fields.

## Validation Commands

Run these from repo root.

### Validate JSON

```bash
node -e "JSON.parse(require('fs').readFileSync('n8n_post_content.json','utf8')); console.log('json ok')"
```

Expected:

```text
json ok
```

### Validate Connections

```bash
node - <<'NODE'
const fs=require('fs');
const j=JSON.parse(fs.readFileSync('n8n_post_content.json','utf8'));
const names=new Set(j.nodes.map(n=>n.name));
let bad=[];
for (const [source, conn] of Object.entries(j.connections||{})) {
  if (!names.has(source)) bad.push(`missing source ${source}`);
  for (const group of conn.main||[]) {
    for (const edge of group||[]) {
      if (!names.has(edge.node)) bad.push(`missing target ${source} -> ${edge.node}`);
    }
  }
}
console.log(bad.join('\n') || 'connections ok');
NODE
```

Expected:

```text
connections ok
```

### Validate No Duplicate Node Names

```bash
node - <<'NODE'
const fs=require('fs');
const j=JSON.parse(fs.readFileSync('n8n_post_content.json','utf8'));
const counts={};
for (const node of j.nodes) counts[node.name]=(counts[node.name]||0)+1;
const duplicates=Object.entries(counts).filter(([, count]) => count > 1);
console.log(duplicates.length ? JSON.stringify(duplicates) : 'no duplicate node names');
NODE
```

Expected:

```text
no duplicate node names
```

### Validate Required Notification Nodes Exist

```bash
node - <<'NODE'
const fs=require('fs');
const j=JSON.parse(fs.readFileSync('n8n_post_content.json','utf8'));
const names=new Set(j.nodes.map(n=>n.name));
const required=[
  'Notify Render Started',
  'Notify Render Completed',
  'Notify Render Failed',
  'Notify Opening Started',
  'Notify Opening Completed',
  'Notify Opening Failed',
  'Notify Subtitle Started',
  'Notify Subtitle Completed',
  'Notify Subtitle Failed',
  'Notify Watermark Started',
  'Notify Watermark Completed',
  'Notify Watermark Failed',
  'Notify Delivery Started',
  'Notify Delivery Completed'
];
const missing=required.filter(name => !names.has(name));
console.log(missing.length ? `missing: ${missing.join(', ')}` : 'notification nodes ok');
NODE
```

Expected:

```text
notification nodes ok
```

## Acceptance Criteria

- [ ] Telegram receives notification when render starts.
- [ ] Telegram receives notification when render completes.
- [ ] Telegram receives notification when render fails.
- [ ] Telegram receives notification when opening starts.
- [ ] Telegram receives notification when opening completes.
- [ ] Telegram receives notification when opening fails.
- [ ] Telegram receives notification when subtitle starts.
- [ ] Telegram receives notification when subtitle completes.
- [ ] Telegram receives notification when subtitle fails.
- [ ] Telegram receives notification when watermark starts.
- [ ] Telegram receives notification when watermark completes.
- [ ] Telegram receives notification when watermark fails.
- [ ] Telegram receives notification when final delivery starts.
- [ ] Telegram receives notification when final delivery completes.
- [ ] Workflow does not send notification on every polling loop.
- [ ] Workflow stops with failed notification when a step status is `failed`.
- [ ] Existing final video delivery still works.
- [ ] Existing final metadata message still works.
- [ ] JSON validation passes.
- [ ] Connection validation passes.
- [ ] No duplicate node names.

