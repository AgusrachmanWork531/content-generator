# TODO: ISSUE_RENDER_API_USE_PAYLOAD_AS_SOURCE_OF_TRUTH

## Plan

### Part 1: Add Render Payload Field
- [x] Add `render_payload: Optional[dict] = None` to `GenerateRequest` or `StepRequest` class
- [x] Test: API accepts requests with `render_payload` field

### Part 2: Validate Render Payload
- [x] Add `normalize_render_payload()` function that:
  - Returns `None` if payload is `None`
  - Requires `start` field
  - Requires `end` field
  - Converts `start` and `end` to float
  - Rejects if `end <= start`
  - Computes canonical `duration = round(end - start, 3)`
  - Preserves optional fields: `clip_index`, `viral_score`, `clip_type`, `hook_3_5_seconds`, `selected_transcript`, `structure`, `why_this_clip_works`, `youtube_metadata`, `subtitle_recommendation`, `editing_recommendation`, `best_cut_note`
  - Returns normalized dict with `start`, `end`, `duration`
- [x] Test: Returns HTTP 400 for invalid payload

### Part 3: Render Directly from Payload Time Range
- [x] Update `create_render_job()` to:
  - Normalize `request.render_payload`
  - If normalized payload exists:
    - Force `num_clips = 1`
    - Add `--crop-start <payload.start>` and `--crop-end <payload.end>` to command
  - If no payload, keep current behavior
- [x] Test: Command includes `--crop-start` and `--crop-end` when payload provided

### Part 4: Save Payload in Job Metadata
- [x] Include `render_payload` in `request_data` before passing to `create_step_job()`
- [x] Test: Job metadata includes normalized `render_payload`

### Part 5: Preserve Payload Metadata for Downstream
- [x] Save normalized payload to `storage/free-viral-shorts/<video_id>/render_payload.json`
- [x] Test: File exists after render completes

### Part 6: Response Shape
- [x] Add optional `render_payload` summary to create render job response
- [x] Test: Response includes payload summary when payload exists

### Validation Steps
- [x] Run syntax validation: `python3 -m py_compile api_server.py`
- [x] Validate payload helper with test cases
- [x] Test invalid payload rejection
- [ ] (Optional) Test API request if service is running
