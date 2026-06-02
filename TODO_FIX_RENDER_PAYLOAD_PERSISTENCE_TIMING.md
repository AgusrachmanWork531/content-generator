# TODO: Fix Render Payload Persistence Timing

## Plan based on ISSUE_FIX_RENDER_PAYLOAD_PERSISTENCE_TIMING.md

### Part 1: Add Payload Persistence Helper ✅
- Location: Near `normalize_render_payload()` function
- Function: `save_render_payload_file(video_id: str, payload: dict) -> Optional[Path]`
- Behavior:
  - Return None if video_id is empty
  - Return None if payload is empty
  - Create OUTPUT_DIR / video_id if needed
  - Write payload JSON to OUTPUT_DIR / video_id / "render_payload.json"
  - Use json.dumps(payload, ensure_ascii=False, indent=2)
  - Return the written Path
  - Let unexpected write errors propagate to caller

### Part 2: Save Payload When Render Job Is Created ✅
- Location: In `create_render_job()`, after normalized_payload is created, before create_step_job()
- Add code:
  ```python
  render_payload_path = None
  if normalized_payload:
      render_payload_path = save_render_payload_file(video_id, normalized_payload)
  ```
- If write fails, return HTTP 500 with clear message

### Part 3: Store Payload Path in Job Metadata ✅
- Location: In request_data when normalized_payload exists
- Add field:
  ```python
  "render_payload_path": "free-viral-shorts/<video_id>/render_payload.json"
  ```
- Use relative path from STORAGE_DIR

### Part 4: Keep Post-Completion Write as Safety Net ✅
- Location: In `run_command_job()` function
- Use new helper `save_render_payload_file()`
- Update error handling to not silently swallow exceptions

### Part 5: Fix Comment Indentation ✅
- Fix dedented comments in touched blocks
- At minimum indent:
  ```python
  # Part 5: Save render_payload.json after render completes
  # Include error if job failed
  ```

## Status: COMPLETED

## Validation Results
- ✅ Syntax validation: `python3 -m py_compile api_server.py`
- ✅ Helper validation: `save_render_payload_file()` works correctly
- ✅ Create render job validation: All assertions pass
  - `render_payload.start` is correct
  - `--crop-start` and `--crop-end` in cmd
  - `render_payload.duration` is 27.8
  - `render_payload_path` in request_data
  - Payload file exists on disk
