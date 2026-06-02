# TODO: Fix Review Issues After Transcript Audio Fallback Implementation

## Status

COMPLETED

## Goal

Fix the remaining bugs found after implementing:

```text
TODO_FIX_TRANSCRIPT_AUDIO_FALLBACK_NO_YOUTUBE_SUBTITLES.md
```

The audio fallback backend is mostly present, but the n8n status flow is broken and transcript output validation is too loose.

## Files To Edit

Edit only:

```text
n8n_node.json
api_server.py
```

Do not edit render, watermark, Telegram video delivery, prompt files, or unrelated scripts.

## Current Bugs To Fix

### Bug 1: Missing n8n node

Current `n8n_node.json` has this broken connection:

```text
Check Status Extract transcribe1 -> If Transcript Status
```

But there is no node named:

```text
If Transcript Status
```

This makes the n8n workflow structurally invalid.

### Bug 2: Wrong chat_id expression

Current node:

```text
Send Transcript Error
```

uses:

```text
={{ $('Parse Source & Video ID').first().json.message.chat.id }}
```

That is wrong because `Parse Source & Video ID` does not output `message.chat.id`.

Use `Telegram Trigger` instead.

### Bug 3: Error message does not include backend error

Current error message only says:

```text
Transcript gagal untuk video ...
```

It must include:

```text
$json.error
```

### Bug 4: Backend transcript output validation is too loose

Current `api_server.py` treats any `*.json` inside:

```text
storage/transcripts/{video_id}
```

as a successful transcript.

This is unsafe because `metadata.json` or `word_timestamps.json` alone can make the job look completed.

## Plan

### Step 1: Fix n8n status node shape

In `n8n_node.json`, find the node named:

```text
if1
```

Rename it to:

```text
If Transcript Status
```

Keep its current IF condition:

```text
status == completed
```

Reason:

- Existing connections already point to `If Transcript Status`.
- Renaming `if1` is simpler than creating another duplicate IF node.

### Step 2: Fix n8n connections

After renaming, update the connections so this is true:

```text
Check Status Extract transcribe1 -> If Transcript Status
```

`If Transcript Status` must have:

```text
true branch  -> Convert to File
false branch -> Wait5
```

Important:

- Do not connect the false branch directly to `Send Transcript Error`.
- The current IF only checks `completed`.
- A non-completed status can be `queued` or `running`, so it must still wait and poll again.

### Step 3: Add a separate failed-status IF node

Add a new IF node named:

```text
If Transcript Failed
```

Condition:

```text
status == failed
```

Use this flow:

```text
Check Status Extract transcribe1
  -> If Transcript Failed
```

Then:

```text
If Transcript Failed true  -> Send Transcript Error
If Transcript Failed false -> If Transcript Status
```

Then:

```text
If Transcript Status true  -> Convert to File
If Transcript Status false -> Wait5
Wait5 -> Check Status Extract transcribe1
```

This prevents infinite polling only when status is truly `failed`.

### Step 4: Fix `Send Transcript Error`

In node:

```text
Send Transcript Error
```

Set `chatId` to:

```text
={{ $('Telegram Trigger').first().json.message.chat.id }}
```

Set `text` to:

```text
={{ 'Transcript gagal untuk video ' + ($json.video_id || $('Parse Source & Video ID').first().json.video_id || '-') + '\n\n' + ($json.error || 'Unknown transcript error') }}
```

Keep Telegram credentials unchanged.

### Step 5: Tighten backend transcript output validation

In `api_server.py`, find:

```python
elif step == "transcript":
```

Replace the loose `*.json` check with this exact behavior:

```python
elif step == "transcript":
    transcript_dir = TRANSCRIPT_DIR / video_id
    required_files = [
        transcript_dir / "transcript.clean.json",
        transcript_dir / "transcript.txt",
        transcript_dir / "transcript.vtt",
    ]
    return all(path.exists() and path.stat().st_size > 0 for path in required_files)
```

Reason:

- `transcript.clean.json` is required by downstream analysis.
- `transcript.txt` is needed for text output.
- `transcript.vtt` proves subtitle timing output exists.

### Step 6: Keep existing audio fallback behavior

Do not rewrite these helpers unless syntax is broken:

```text
find_downloaded_video
run_audio_fallback_transcription
convert_word_timestamps_to_transcript_files
run_transcript_job_with_audio_fallback
```

Only fix the validation logic in `step_output_exists()`.

## Validation Commands

Run from repo root.

### Validate n8n JSON

```bash
node -e "JSON.parse(require('fs').readFileSync('n8n_node.json','utf8')); console.log('json ok')"
```

Expected:

```text
json ok
```

### Validate n8n connections

Run:

```bash
node - <<'NODE'
const fs=require('fs');
const j=JSON.parse(fs.readFileSync('n8n_node.json','utf8'));
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

### Validate Python syntax

```bash
python3 -m py_compile api_server.py
```

Expected: no output.

### Validate transcript output check

Use a temporary video id folder:

```bash
mkdir -p storage/transcripts/TEST_TRANSCRIPT_CHECK
echo '{}' > storage/transcripts/TEST_TRANSCRIPT_CHECK/metadata.json
python3 - <<'PY'
import api_server
print(api_server.step_output_exists("transcript", "TEST_TRANSCRIPT_CHECK"))
PY
```

Expected:

```text
False
```

Then add required files:

```bash
echo '[]' > storage/transcripts/TEST_TRANSCRIPT_CHECK/transcript.clean.json
echo 'hello' > storage/transcripts/TEST_TRANSCRIPT_CHECK/transcript.txt
echo 'WEBVTT' > storage/transcripts/TEST_TRANSCRIPT_CHECK/transcript.vtt
python3 - <<'PY'
import api_server
print(api_server.step_output_exists("transcript", "TEST_TRANSCRIPT_CHECK"))
PY
```

Expected:

```text
True
```

## Acceptance Criteria

- [ ] No n8n connection references a missing node.
- [ ] `Check Status Extract transcribe1` first checks `failed`.
- [ ] Failed transcript jobs go to `Send Transcript Error`.
- [ ] Running or queued transcript jobs go to `Wait5`.
- [ ] Completed transcript jobs go to `Convert to File`.
- [ ] `Send Transcript Error` uses chat id from `Telegram Trigger`.
- [ ] `Send Transcript Error` includes `$json.error`.
- [ ] `step_output_exists("transcript", video_id)` requires `transcript.clean.json`, `transcript.txt`, and `transcript.vtt`.
- [ ] Python syntax validation passes.
- [ ] n8n JSON validation passes.

