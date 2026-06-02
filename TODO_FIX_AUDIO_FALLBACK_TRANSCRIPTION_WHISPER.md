# TODO: Fix Audio Fallback Transcription Missing Whisper Module

## Issue
Transcript failed for video `h6pQeHZNaYo`:
- YouTube transcript failed (no subtitles available)
- Audio fallback failed: `ModuleNotFoundError: No module named 'whisper'`

## Root Cause
In `api_server.py`, the `run_audio_fallback_transcription()` function uses `CV_PYTHON_BIN` which defaults to `sys.executable` (the API venv `.venv-api`). However, `whisper` is installed in the transcript venv (`.venv-transcript-api`), not in the API venv.

Current:
- `api_server.py`: `CV_PYTHON_BIN = os.environ.get("CV_PYTHON_BIN", sys.executable)`
- `run_service.sh`: `export CV_PYTHON_BIN="${CV_PYTHON_BIN:-$VENV_API_DIR/bin/python}"`
- Result: Uses `.venv-api` which doesn't have `whisper`

## Fix Plan

### Option 1: Update api_server.py to use SUBTITLE_AUTOCAPTIONS_PYTHON (Recommended)
Change `run_audio_fallback_transcription()` to use `SUBTITLE_AUTOCAPTIONS_PYTHON` env var which is already properly configured in run_service.sh:

```python
# Instead of CV_PYTHON_BIN, use SUBTITLE_AUTOCAPTIONS_PYTHON
FALLBACK_PYTHON_BIN = os.environ.get(
    "SUBTITLE_AUTOCAPTIONS_PYTHON",
    os.environ.get("VENV_DIR", str(APP_DIR / ".venv-transcript-api")) + "/bin/python"
)
```

### Option 2: Change run_service.sh default for CV_PYTHON_BIN
Change default in run_service.sh from API venv to transcript venv:
- Current: `export CV_PYTHON_BIN="${CV_PYTHON_BIN:-$VENV_API_DIR/bin/python}"`
- Proposed: `export CV_PYTHON_BIN="${CV_PYTHON_BIN:-$VENV_DIR/bin/python}"`

However this might break other parts of the pipeline that need the API venv.

## Implementation Steps

- [ ] 1. Update api_server.py to use SUBTITLE_AUTOCAPTIONS_PYTHON for audio fallback
- [ ] 2. Verify whisper can be imported with the new path
- [ ] 3. Test audio fallback transcription

## Verification Commands
```bash
# Check whisper in transcript venv
.venv-transcript-api/bin/python -c "import whisper; print('ok')"

# Test the fix
# Run a transcript job that falls back to audio
