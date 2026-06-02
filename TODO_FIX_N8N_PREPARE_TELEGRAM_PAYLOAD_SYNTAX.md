# TODO: Fix N8N Prepare Telegram Payload Syntax Error

## Status: PLANNED

## Error

`Prepare Telegram Payload` fails with:

```text
Unexpected token ';' [line 68]
```

## Root Cause

The code node return statement is malformed.

Current broken ending:

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
};
```

The array and object are not closed correctly before the semicolon.

## Required Fix

Replace the ending with:

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

## Additional Checks

- [ ] Verify the full `Prepare Telegram Payload` JavaScript parses without syntax errors.
- [ ] Verify `n8n_node.json` remains valid JSON after editing.
- [ ] Confirm `Get Watermark Result` connects to `Prepare Telegram Payload`.
- [ ] Confirm `Prepare Telegram Payload` outputs:
  - `chat_id`
  - `video_id`
  - `video_path`
  - `caption`
  - `metadata_text`
  - `filename`
- [ ] Confirm `Read Binary File` uses:

```text
={{ $json.video_path }}
```

## Suggested Safer Code Ending

Use this ending in the code node:

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

## Acceptance Criteria

- [ ] `Prepare Telegram Payload` no longer throws `Unexpected token ';'`.
- [ ] The node returns one valid n8n item.
- [ ] The next node can read `video_path`.
- [ ] Telegram video and metadata nodes receive the expected fields.
