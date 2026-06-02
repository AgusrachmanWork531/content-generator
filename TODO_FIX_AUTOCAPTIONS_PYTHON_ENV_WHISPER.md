# TODO: Fix Auto-Captions Python Environment Missing Whisper

## Issue
Subtitle generation fails with `ModuleNotFoundError: No module named 'whisper'` because `autocaptions_adapter.py` hard-codes `python3`.

## Implementation Steps

- [ ] 1. Add imports (os, sys) in autocaptions_adapter.py
- [ ] 2. Add _python_can_import() helper method
- [ ] 3. Add _resolve_auto_captions_python() helper method
- [ ] 4. Replace "python3" with resolver in _run_caption_generator()
- [ ] 5. Replace "python3" with resolver in _run_json_to_ass()
- [ ] 6. Update run_service.sh with SUBTITLE_AUTOCAPTIONS_PYTHON export
- [ ] 7. Verify changes compile

## Verification Commands
```bash
.venv-transcript-api/bin/python -c "import whisper, torch; print('ok')"
python3 -m py_compile subtitle_service/autocaptions_adapter.py
bash -n tools/service/run_service.sh
