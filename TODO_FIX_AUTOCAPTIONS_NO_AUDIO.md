# TODO: Fix Auto-Captions No Audio Stream Error

## Error
```
[AutoCaptions] Using SUBTITLE_AUTOCAPTIONS_PYTHON for auto-captions: /Users/agusrachman/Documents/Codex/content-short/.venv-transcript-api/bin/python
[PackageEngine] Auto-captions FAILED: Package execution failed: auto-captions
Output file does not contain any stream
Error opening output files: Invalid argument
```

## Root Cause

The rendered short (`short_01.mp4`) has NO audio stream:
- Input video (source): has Video+Audio (av1 + aac, 44100Hz)
- Rendered short: Video ONLY (h264, 3462 kb/s video, no audio)

When auto-captions runs FFmpeg to extract audio, it fails because there's no audio track to extract.

## Investigation Summary

| File | Video | Audio |
|------|-------|-------|
| source video | ✓ av1, 1330kb/s | ✓ aac, 44100Hz stereo |
| short_01.mp4 | ✓ h264, 3462kb/s | ✗ NO AUDIO |

## Fix Applied

### Option A: Fix render_shorts to include audio (RECOMMENDED - fix root cause)
In `tools/media/free_viral_shorts.sh`, added `-map 0:v -map 0:a` to both FFmpeg commands:

1. First FFmpeg command (source clip extraction):
```bash
ffmpeg ... -map 0:v -map 0:a -c:v libx264 -c:a aac -b:a 128k source_clip.mp4
```

2. Second FFmpeg command (final filter):
```bash
ffmpeg ... -map 0:v -map 0:a -vf final_video_filter -c:v libx264 -c:a aac -b:a 128k final_file.mp4
```

The `-map 0:v` and `-map 0:a` flags explicitly tell FFmpeg to include both video and audio streams from the input.

## Status
- [x] Implement Option A (render_shorts fix)
- [ ] Implement Option B as safety net (auto-captions fallback) - OPTIONAL, only if needed

## Note
Run `free_viral_shorts.sh` again to regenerate shorts with audio. The fix is already applied.
