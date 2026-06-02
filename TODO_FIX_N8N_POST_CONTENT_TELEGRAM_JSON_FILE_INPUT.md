# TODO: Fix N8N Post Content Telegram JSON File Input

## Status

OPEN

## Goal

Fix `n8n_post_content.json` so `Telegram Trigger1 -> Code in JavaScript2` can accept the render payload when the user sends it as:

- Telegram text message containing JSON
- Telegram document/file containing `.json`

Current error:

```text
Telegram message.text kosong atau tidak ditemukan. | {"available_keys":["update_id","message"]} [line 7]
```

This happens because `Code in JavaScript2` only reads:

```js
item.json?.message?.text
```

When the user uploads a JSON file, Telegram sends `message.document`, not `message.text`.

## File To Edit

Edit only:

```text
n8n_post_content.json
```

Do not edit:

```text
api_server.py
n8n_node.json
n8n_node_fixed.json
tools/media/free_viral_shorts.sh
```

## Required Fix

### Step 1: Enable File Download In `Telegram Trigger1`

Find node:

```text
Telegram Trigger1
```

Change:

```json
"additionalFields": {}
```

to:

```json
"additionalFields": {
  "download": true
}
```

This is required so uploaded `.json` files are available in `item.binary`.

### Step 2: Replace Text-Only Parser In `Code in JavaScript2`

Find node:

```text
Code in JavaScript2
```

Replace its `parameters.jsCode` with a parser that supports both:

1. `item.json.message.text`
2. uploaded JSON file from `item.binary`

Use the already-working implementation from:

```text
n8n_node.json
node name: Code in JavaScript3
```

Copy the full `parameters.jsCode` from that node into:

```text
n8n_post_content.json
node name: Code in JavaScript2
```

Important:

- Do not rename `Code in JavaScript2`.
- Do not rename downstream nodes.
- Do not change any downstream references like:

```js
$('Code in JavaScript2').first().json
```

The replacement code must contain these functions or equivalent logic:

```js
async function getRawPayloadText(item, itemIndex, helpers) {
  const binaryKeys = Object.keys(item.binary || {});

  if (binaryKeys.length > 0) {
    const binaryPropertyName = binaryKeys.includes('data') ? 'data' : binaryKeys[0];
    const binaryMeta = item.binary[binaryPropertyName] || {};
    const fileName =
      binaryMeta.fileName ||
      item.json?.message?.document?.file_name ||
      item.json?.message?.document?.fileName ||
      null;

    const buffer = await helpers.getBinaryDataBuffer(itemIndex, binaryPropertyName);
    const raw = buffer.toString('utf8').trim();

    if (!isNonEmptyString(raw)) {
      fail('File JSON Telegram kosong atau tidak bisa dibaca sebagai UTF-8.', {
        binary_property: binaryPropertyName,
        file_name: fileName
      });
    }

    return {
      raw,
      input_type: 'telegram_json_file',
      binary_property: binaryPropertyName,
      file_name: fileName
    };
  }

  const text = item.json?.message?.text;

  if (isNonEmptyString(text)) {
    return {
      raw: text.trim(),
      input_type: 'telegram_text',
      binary_property: null,
      file_name: null
    };
  }

  fail('Payload Telegram tidak ditemukan. Kirim JSON sebagai message.text atau upload file .json, dan pastikan Telegram Trigger1 Additional Fields > Download aktif.', {
    available_json_keys: Object.keys(item.json || {}),
    has_binary: Boolean(item.binary),
    document: item.json?.message?.document || null
  });
}
```

And the loop must use:

```js
const items = $input.all();

for (let index = 0; index < items.length; index++) {
  const item = items[index];
  const rawInput = await getRawPayloadText(item, index, this.helpers);
  const payload = parsePayload(rawInput);
  const validationResult = validatePayload(payload);
  const message = item.json?.message || {};

  // push output...
}
```

## Required Output Shape

The output from `Code in JavaScript2` must still include these fields because downstream nodes depend on them:

```text
source
video_id
num_clips
quality
languages
render_payload
source_video
telegram
validation
```

The `telegram` object should include these additional fields:

```text
input_type
file_name
binary_property
```

Expected `telegram` output shape:

```js
telegram: {
  update_id: item.json?.update_id ?? null,
  message_id: message.message_id ?? null,
  chat_id: message.chat?.id ?? null,
  username: message.from?.username ?? null,
  first_name: message.from?.first_name ?? null,
  last_name: message.from?.last_name ?? null,
  input_type: rawInput.input_type,
  file_name: rawInput.file_name,
  binary_property: rawInput.binary_property
}
```

## Important Validation Detail

The `video_id` extractor should support this extra location:

```js
payload.render_payload?.source_video?.video_id
```

So this logic should be present:

```js
const videoId = extractYoutubeVideoId(
  payload.source ||
  payload.video_id ||
  payload.source_video?.video_id ||
  payload.render_payload?.source_video?.video_id
);
```

## Do Not Change

Do not change these workflow parts:

- Render request
- Opening request
- Subtitle path logic
- Watermark request
- `Prepare Telegram Payload`
- `Download Watermark Video`
- `Send a video`
- `Send a text message`
- Any node names
- Any credentials
- Any ngrok URL

This issue is only for fixing Telegram JSON input parsing.

## Acceptance Checks

Run these checks after editing:

```bash
python3 -m json.tool n8n_post_content.json >/tmp/n8n_post_content_check.json
```

Then verify with Python:

```bash
python3 -c "import json; d=json.load(open('n8n_post_content.json')); t=next(n for n in d['nodes'] if n['name']=='Telegram Trigger1'); c=next(n for n in d['nodes'] if n['name']=='Code in JavaScript2'); assert t['parameters']['additionalFields']['download'] is True; code=c['parameters']['jsCode']; assert 'getBinaryDataBuffer' in code; assert 'telegram_json_file' in code; assert 'message.text' in code; assert 'payload.render_payload?.source_video?.video_id' in code; print('OK')"
```

Expected output:

```text
OK
```

## Manual Test In N8N

Test 1:

1. Send JSON payload as Telegram text.
2. Workflow should pass `Code in JavaScript2`.
3. `telegram.input_type` should be:

```text
telegram_text
```

Test 2:

1. Upload the same payload as `.json` file in Telegram.
2. Workflow should pass `Code in JavaScript2`.
3. `telegram.input_type` should be:

```text
telegram_json_file
```

The old error must not appear anymore:

```text
Telegram message.text kosong atau tidak ditemukan
```
