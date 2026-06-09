# Plan: Fix `generate_transcribe.py` FastAPI Import Failure

## Issue

Running:

```bash
./generate_transcribe.py 3mLbMqNlIgM
```

fails during the first pipeline step:

```text
ModuleNotFoundError: No module named 'fastapi'
```

The traceback shows `generate_transcribe.py` imports `find_downloaded_video` from `api_server.py`. Importing `api_server.py` immediately imports FastAPI and initializes API-only modules, so the standalone transcription CLI cannot run unless the API server dependencies are installed in the active Python environment.

## Findings

- `requirements.txt` already includes `fastapi`, so installing API requirements would make the immediate error disappear.
- The CLI should not need FastAPI just to locate a downloaded video or convert Whisper word timestamps.
- `generate_transcribe.py` uses:
  - `find_downloaded_video`
  - `convert_word_timestamps_to_transcript_files`
- Those helpers currently live in `api_server.py`, which has import-time side effects:
  - imports FastAPI and Pydantic
  - creates the FastAPI app
  - loads subtitle router settings
  - creates storage directories
- There is also a path mismatch:
  - `api_server.py` uses `storage/transcripts`
  - `generate_transcribe.py` currently checks/writes `storage/transcript`
  - `tools/youtube/transcribe_youtube.sh` defaults to `storage/transcripts`

## Recommended Fix

Extract transcription-file helpers into a dependency-light shared module, then make both the API server and CLI import from that module.

Suggested new module:

```text
transcript_utils.py
```

Responsibilities:

- define repo/storage defaults without FastAPI
- find downloaded video files in `storage/video`
- convert `word_timestamps.json` into:
  - `transcript.clean.json`
  - `transcript.raw.json`
  - `transcript.txt`
  - `transcript.paragraphs.txt`
  - `transcript.srt`
  - `transcript.vtt`
  - `metadata.json`

Keep API-specific job handling, routes, auth, and background task logic in `api_server.py`.

## Implementation Steps

1. Create `transcript_utils.py`.
   - Move or copy `find_downloaded_video` from `api_server.py`.
   - Move or copy `convert_word_timestamps_to_transcript_files` from `api_server.py`.
   - Add constants:
     - `APP_DIR = Path(__file__).resolve().parent`
     - `STORAGE_DIR = Path(os.environ.get("CONTENT_SHORT_STORAGE_DIR", APP_DIR / "storage")).resolve()`
     - `TRANSCRIPT_DIR = STORAGE_DIR / "transcripts"`
     - `VIDEO_DIR = STORAGE_DIR / "video"`

2. Update `api_server.py`.
   - Import the shared helpers:
     ```python
     from transcript_utils import find_downloaded_video, convert_word_timestamps_to_transcript_files
     ```
   - Remove the duplicate helper definitions from `api_server.py`, or leave thin wrappers only if needed for backward compatibility.
   - Keep `run_audio_fallback_transcription` in `api_server.py` for now if it still depends on API/server configuration.

3. Update `generate_transcribe.py`.
   - Replace:
     ```python
     from api_server import find_downloaded_video
     ```
     with:
     ```python
     from transcript_utils import find_downloaded_video
     ```
   - Replace the fallback conversion import with:
     ```python
     from transcript_utils import convert_word_timestamps_to_transcript_files
     ```
   - Remove the unused import of `run_audio_fallback_transcription`.
   - Change transcript output directory from `storage/transcript` to `storage/transcripts`.

4. Check Whisper fallback path compatibility.
   - `generate_transcribe.py` runs `tools/audio/transcribe_audio_whisper.sh`.
   - Confirm that script writes `word_timestamps.json` into the same directory expected by `convert_word_timestamps_to_transcript_files`.
   - If the script writes to `storage/transcript`, update the script call or converter path so all transcript outputs use `storage/transcripts`.

5. Add lightweight validation.
   - Add a syntax/import check that does not require FastAPI:
     ```bash
     python3 -c "from transcript_utils import find_downloaded_video, convert_word_timestamps_to_transcript_files; print('ok')"
     ```
   - Run:
     ```bash
     python3 -m py_compile generate_transcribe.py transcript_utils.py
     ```
   - Run the CLI far enough to confirm it no longer fails on `fastapi` import.

## Alternative Short-Term Fix

Install dependencies into the active environment:

```bash
python3 -m pip install -r requirements.txt
```

This is faster, but it keeps the standalone CLI coupled to API server dependencies. It also does not address the `storage/transcript` vs `storage/transcripts` mismatch.

## Acceptance Criteria

- `./generate_transcribe.py 3mLbMqNlIgM` no longer imports `api_server.py`.
- Running the CLI without FastAPI installed does not fail at startup.
- The transcript output path is consistently `storage/transcripts/<video_id>/transcript.clean.json`.
- Existing API transcript fallback behavior still works.
- `py_compile` passes for changed Python files.

## Risk Notes

- `api_server.py` has several existing local modifications in the worktree, so implementation should be done carefully with minimal edits.
- If downstream scripts or n8n flows still reference `storage/transcript`, update those references or add a migration/compatibility note.
- Avoid deleting existing transcript folders until path usage is confirmed.
