# TODO: Fix Pipeline Paths After Tools Relocation

## Status: COMPLETED

## Files Edited
- [x] tools/service/run.sh
- [x] tools/media/free_viral_shorts.sh
- [x] tools/media/watermark_shorts.sh
- [x] n8n_node.json

## Edit Plan

### Part 1: `tools/service/run.sh`
- [x] 1. Add `REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"` after SCRIPT_DIR
- [x] 2. Change `absolute_path` to use `$REPO_ROOT` instead of `$SCRIPT_DIR`
- [x] 3. Replace viral pipeline call with `$REPO_ROOT/tools/media/free_viral_shorts.sh`
- [x] 4. Replace watermark call with `$REPO_ROOT/tools/media/watermark_shorts.sh`

### Part 2: `tools/media/free_viral_shorts.sh`
- [x] 1. Add `REPO_ROOT` after SCRIPT_DIR
- [x] 2. Change `absolute_path` to use `$REPO_ROOT`
- [x] 3. Fix Python venv lookup to use `$REPO_ROOT/.venv-api`
- [x] 4. Fix helper script paths to use `$REPO_ROOT/tools/youtube/...`
- [x] 5. Fix Python script paths to use `$REPO_ROOT/scripts/...`
- [x] 6. Fix cache path to use `$REPO_ROOT/.local-cache`

### Part 3: `tools/media/watermark_shorts.sh`
- [x] 1. Add `REPO_ROOT` after SCRIPT_DIR
- [x] 2. Change `absolute_path` to use `$REPO_ROOT`
- [x] 3. Fix assets directory to use `$REPO_ROOT/assets/watermark`
- [x] 4. Fix generator path to use `$REPO_ROOT/scripts/watermark_generator.py`

### Part 4: `n8n_node.json`
- [x] 1. Remove the "Upload To YouTube" → "Trigger Opening Narration" connection
- [x] 2. Verify JSON is valid

## Verification Results
- tools/service/run.sh: Shell syntax OK
- tools/media/free_viral_shorts.sh: Shell syntax OK
- tools/media/watermark_shorts.sh: Shell syntax OK
- n8n_node.json: Valid JSON, Upload To YouTube has no outgoing connections
