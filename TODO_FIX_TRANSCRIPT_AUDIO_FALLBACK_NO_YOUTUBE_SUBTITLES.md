# TODO: Fix Transcript Step When YouTube Has No Subtitles

## Status

PLANNED

## Error Example

Step `Ekstract Trunscribe1` / `/jobs/steps/transcript` can fail with:

```text
Subtitles are disabled for this video
No .vtt/.srt subtitle file found
```

Example failed video:

```text
h6pQeHZNaYo
```

## Root Cause

The transcript step currently tries:

1. `youtube-transcript-api`
2. `yt-dlp` subtitle fallback
3. local `.vtt/.srt` subtitle cache

If the video has no YouTube captions, all three can fail. The backend does not yet fallback to audio transcription.

## Goal

When YouTube captions are not available, the transcript step must fallback to local audio transcription and still create:

```text
storage/transcripts/{video_id}/transcript.clean.json
storage/transcripts/{video_id}/transcript.raw.json
storage/transcripts/{video_id}/transcript.txt
storage/transcripts/{video_id}/transcript.paragraphs.txt
storage/transcripts/{video_id}/transcript.srt
storage/transcripts/{video_id}/transcript.vtt
storage/transcripts/{video_id}/metadata.json
```

If audio fallback also fails, n8n must stop polling forever and send a clear Telegram error message.

## Files To Edit

Edit only these files:

```text
api_server.py
n8n_node.json
```

Do not edit prompt files, render payload logic, watermark logic, or Telegram video delivery logic.

## Backend Fix: `api_server.py`

### Step 1: Add a helper to find downloaded source video

Add a helper near `step_output_exists()` or other video helpers:

```python
def find_downloaded_video(video_id: str) -> Optional[Path]:
    extensions = {".mp4", ".mkv", ".webm", ".mov"}
    if not VIDEO_DIR.exists():
        return None

    matches = [
        path
        for path in VIDEO_DIR.iterdir()
        if path.is_file()
        and video_id in path.name
        and path.suffix.lower() in extensions
        and path.stat().st_size > 0
    ]
    matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0] if matches else None
```

### Step 2: Add audio fallback helper

Add a helper that runs existing auto-captions Whisper tooling.

Use these defaults:

```text
model: medium
preset: accurate
audio_preset: speech
language: first language from request.languages, e.g. id from id,en
```

Command to run:

```python
[
    CV_PYTHON_BIN,
    "external_packages/auto-captions/caption_generator.py",
    "-i", str(video_path),
    "-a", str(transcript_dir / "audio.wav"),
    "-o", str(transcript_dir / "word_timestamps.json"),
    "-m", "medium",
    "-l", language,
    "--preset", "accurate",
    "--audio-preset", "speech",
    "--save-raw-result",
]
```

Important:

- Use `subprocess.run(..., capture_output=True, text=True, timeout=1800)`.
- If command fails, raise an error containing stdout/stderr.
- Do not add a new dependency. Use existing `external_packages/auto-captions/caption_generator.py`.

### Step 3: Convert Whisper output to transcript files

After `word_timestamps.json` is created, convert it into transcript segments.

Input format:

```json
[
  { "word": "kata", "start": 0.1, "end": 0.5 }
]
```

Simple conversion rule:

- Group words into segments of about 12 words.
- Start time = first word start.
- End time = last word end.
- Text = joined words.

Write these files:

```text
transcript.raw.json
transcript.clean.json
transcript.txt
transcript.paragraphs.txt
transcript.srt
transcript.vtt
metadata.json
```

Metadata must include:

```json
{
  "source_method": "audio-whisper-fallback",
  "video_id": "...",
  "requested_languages": ["id", "en"],
  "selected_transcript": {
    "video_id": "...",
    "language_code": "id",
    "is_generated": true,
    "is_translatable": false,
    "translated_to": null
  }
}
```

### Step 4: Make `/jobs/steps/transcript` use fallback automatically

Current endpoint builds this command:

```python
cmd = [
    "./transcribe_youtube.sh",
    "-o", str(TRANSCRIPT_DIR),
    "-l", str(request.languages),
    request.source,
]
```

Keep this command as the first attempt.

Change transcript job execution so:

1. Run `./transcribe_youtube.sh`.
2. If it succeeds, job is `completed`.
3. If it fails, call the audio fallback helper.
4. If audio fallback succeeds, job is `completed`.
5. If audio fallback fails, job is `failed`.

Simplest implementation:

- Add a new background function only for transcript jobs, for example:

```python
def run_transcript_job_with_audio_fallback(job_id: str, video_id: str, request_data: dict, cmd: list[str]):
    ...
```

- Use this function only inside `create_transcript_job()`.
- Do not change generic `run_command_job()` for other steps.

## N8N Fix: `n8n_node.json`

### Step 1: Find these nodes

```text
Ekstract Trunscribe1
Check Status Extract transcribe1
if1
Wait5
```

### Step 2: Prevent infinite polling on failed transcript job

Current logic only checks:

```text
status == completed
```

Add a failed-status branch.

Expected behavior:

- If `status == completed`: continue to `Convert to File`.
- If `status == failed`: send Telegram error message and stop.
- Otherwise: wait via `Wait5`, then check status again.

### Step 3: Add Telegram error node

Add a Telegram node named:

```text
Send Transcript Error
```

Use:

```json
{
  "chatId": "={{ $('Telegram Trigger').first().json.message.chat.id }}",
  "text": "={{ 'Transcript gagal untuk video ' + $json.video_id + '\\n\\n' + ($json.error || 'Unknown error') }}"
}
```

Connect failed branch to this node.

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

### Validate Python syntax

```bash
python3 -m py_compile api_server.py
```

Expected: no output.

### Manual transcript test

Make sure the source video exists first:

```bash
./download_youtube_hd.sh -q 1080 -o storage/video https://youtu.be/h6pQeHZNaYo
```

Then call transcript job through API or run the same logic. Expected output files:

```text
storage/transcripts/h6pQeHZNaYo/transcript.clean.json
storage/transcripts/h6pQeHZNaYo/transcript.txt
storage/transcripts/h6pQeHZNaYo/transcript.srt
storage/transcripts/h6pQeHZNaYo/transcript.vtt
storage/transcripts/h6pQeHZNaYo/metadata.json
```

## Acceptance Criteria

- [ ] Video with YouTube captions still completes using existing transcript flow.
- [ ] Video `h6pQeHZNaYo` completes using `audio-whisper-fallback`.
- [ ] `metadata.json` records `source_method: audio-whisper-fallback`.
- [ ] Transcript output files are created in `storage/transcripts/{video_id}`.
- [ ] n8n does not wait forever when transcript job status is `failed`.
- [ ] n8n sends a Telegram error message if all transcript methods fail.
- [ ] No watermark, render, or Telegram video delivery nodes are changed.

