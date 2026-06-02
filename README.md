# Content Short - YouTube Shorts Processor

Automated pipeline for creating and uploading YouTube Shorts with subtitles, watermarks, and narrations.

## Project Structure

```
content-short/
├── app/                  # Source code
│   └── subtitle_service/  # Core subtitle generation service
├── scripts/              # CLI utilities
│   └── subtitle_pipeline/  # Pipeline components
├── tools/               # Operational shell scripts
│   ├── service/        # Service run scripts
│   ├── youtube/       # YouTube download/upload
│   └── media/        # Media processing
├── docs/               # Documentation
│   ├── issues/       # Issue tracking
│   ├── todos/       # Task tracking
│   ├── reports/     # Analysis reports
│   ├── plans/      # Project plans
│   └── guides/     # User guides
├── config/            # Configuration files
├── assets/           # Fonts, BGM, watermarks
├── storage/          # Generated/runtime output (git-ignored)
│   ├── api-jobs/   # API job outputs
│   ├── subtitle-jobs/ # Subtitle outputs
│   └── video/     # Processed videos
└── external_packages/  # Vendor/local packages
```

## Quick Start

```bash
# Show help
python scripts/generate_subtitle.py --help

# Full pipeline
./run.sh

# Run service only
./run_service.sh
```

## Requirements

- Python 3.11+
- FFmpeg
- Whisper (for transcription)
- Google Cloud credentials (for upload)

## Documentation

See `docs/guides/` for detailed guides.
