# Content Short — Installation Guide

> Multi-platform installation untuk **macOS**, **Linux (Ubuntu/Debian)**, dan **Windows (WSL2)**.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [System Dependencies](#system-dependencies)
- [Clone Repository](#clone-repository)
- [Python Virtual Environments](#python-virtual-environments)
- [External Packages](#external-packages)
- [Environment Variables](#environment-variables)
- [Storage Directories](#storage-directories)
- [Assets](#assets)
- [Ngrok Setup (Opsional)](#ngrok-setup-opsional)
- [Docker Deployment](#docker-deployment)
- [Menjalankan Service](#menjalankan-service)
- [Verifikasi Instalasi](#verifikasi-instalasi)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Komponen | Versi Minimum | Keterangan |
|:---|:---|:---|
| **Python** | 3.11+ | Wajib. Digunakan untuk API server dan semua script |
| **FFmpeg** | 5.0+ | Wajib. Harus mendukung `libass` untuk subtitle burn |
| **yt-dlp** | latest | Wajib. Download video YouTube |
| **Git** | 2.30+ | Wajib. Clone repo dan external packages |
| **curl** | any | Wajib. Health check dan download |
| **ngrok** | 3.x | Opsional. Tunnel publik untuk n8n webhook |
| **Docker** | 20.10+ | Opsional. Alternatif deployment via container |
| **Node.js** | — | Opsional. Hanya jika integrasi n8n di lokal |

---

## System Dependencies

### macOS (Homebrew)

```bash
# Homebrew (jika belum ada)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Core dependencies
brew install python@3.11 ffmpeg yt-dlp git curl

# FFmpeg dengan libass (untuk subtitle burn)
brew install ffmpeg --with-libass
# atau gunakan ffmpeg-full jika tersedia:
brew tap homebrew-ffmpeg/ffmpeg
brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libass

# Ngrok (opsional)
brew install ngrok/ngrok/ngrok
```

### Linux (Ubuntu/Debian)

```bash
# Update package list
sudo apt update && sudo apt upgrade -y

# Core dependencies
sudo apt install -y \
    python3.11 python3.11-venv python3.11-dev \
    ffmpeg \
    git curl wget \
    build-essential \
    libass-dev

# yt-dlp (latest binary)
sudo curl -sL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && sudo chmod a+rx /usr/local/bin/yt-dlp

# Ngrok (opsional)
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok-v3-stable-linux-amd64.tgz \
    | sudo tar xz -C /usr/local/bin
```

### Windows (WSL2)

```powershell
# 1. Install WSL2 terlebih dahulu (PowerShell as Admin)
wsl --install -d Ubuntu-22.04

# 2. Masuk ke WSL
wsl
```

```bash
# Di dalam WSL Ubuntu — ikuti langkah Linux di atas
sudo apt update && sudo apt install -y \
    python3.11 python3.11-venv python3.11-dev \
    ffmpeg git curl wget build-essential libass-dev

# yt-dlp
sudo curl -sL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && sudo chmod a+rx /usr/local/bin/yt-dlp
```

> **Catatan Windows**: Proyek ini menggunakan bash scripts secara intensif. Jalankan semua perintah di dalam WSL2, bukan di native Windows CMD/PowerShell.

---

## Clone Repository

```bash
git clone <REPO_URL> content-short
cd content-short
```

---

## Python Virtual Environments

Proyek ini memerlukan **dua** virtual environment terpisah:

### 1. API Server Venv (`.venv-api`)

```bash
python3.11 -m venv .venv-api
source .venv-api/bin/activate    # Linux/macOS
# .venv-api\Scripts\activate     # Windows (jika tanpa WSL)

pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

**Packages dalam `requirements.txt`:**

| Package | Fungsi |
|:---|:---|
| `fastapi` | Web framework async untuk API server |
| `uvicorn[standard]` | ASGI server |
| `python-multipart` | Form/file upload handling |
| `pydantic` | Data validation & model |
| `pydantic-settings` | Environment-based configuration |
| `youtube-transcript-api` | Ekstraksi transcript YouTube |
| `opencv-python-headless` | Visual layout analysis |
| `numpy` | Komputasi numerik |
| `pillow` | Image processing (thumbnail, watermark) |
| `edge-tts` | Text-to-Speech untuk opening narration |
| `pyautoflip==0.2.1` | Auto-flip video aspect ratio |
| `google-api-python-client` | Google Drive/YouTube API |
| `google-auth-oauthlib` | Google OAuth2 authentication |
| `google-auth-httplib2` | Google HTTP transport |

### 2. Transcript Venv (`.venv-transcript-api`)

Venv terpisah untuk Whisper audio fallback transcription.

```bash
python3.11 -m venv .venv-transcript-api
source .venv-transcript-api/bin/activate

pip install --upgrade pip wheel "setuptools<82"
pip install youtube-transcript-api

# Opsional: Whisper untuk audio fallback (memerlukan torch)
# pip install openai-whisper
# pip install whisperx  # atau install via git:
# pip install git+https://github.com/m-bain/whisperX.git
```

---

## External Packages

Beberapa package di-install sebagai git submodule/clone ke `external_packages/`:

### auto-captions (Primary Subtitle Engine)

```bash
mkdir -p external_packages
cd external_packages

# Clone auto-captions
git clone https://github.com/nikhil-reddy05/auto-captions.git

cd auto-captions
# Install dependencies ke dalam transcript venv
source ../../.venv-transcript-api/bin/activate
pip install -r requirements.txt   # jika ada
deactivate

cd ../..
```

### Opsional: WhisperX / Captions

```bash
# WhisperX (fallback engine)
cd external_packages
git clone https://github.com/m-bain/whisperX.git
cd whisperX
source ../../.venv-transcript-api/bin/activate
pip install -e .
deactivate
cd ../..

# Captions (format converter)
cd external_packages
git clone https://github.com/lattifai/captions.git
cd ../..
```

---

## Environment Variables

Buat file `.env` di root proyek:

```bash
cp .env.example .env   # jika ada, atau buat manual
```

```dotenv
# ── API Server ──────────────────────────────────────
CONTENT_SHORT_API_TOKEN=your-secret-api-token
CONTENT_SHORT_BASE_URL=http://127.0.0.1:8088

# ── FFmpeg ──────────────────────────────────────────
# macOS Homebrew:
FFMPEG_BIN=/opt/homebrew/bin/ffmpeg
# Linux:
# FFMPEG_BIN=/usr/bin/ffmpeg

# ── Ngrok (opsional, untuk public webhook) ──────────
NGROK_TOKEN=your-ngrok-authtoken
NGROK_DOMAIN=your-subdomain.ngrok-free.dev
NGROK_TARGET_PORT=8088

# ── Webhook URL (set otomatis oleh run_service.sh) ──
WEBHOOK_URL=http://127.0.0.1:8088

# ── YouTube Data API (untuk trending) ──────────────
API_KEY_YOUTUBE=your-youtube-api-key
```

### Variabel Environment Lengkap

| Variabel | Default | Keterangan |
|:---|:---|:---|
| `CONTENT_SHORT_API_TOKEN` | `change-me` | Bearer token untuk auth API |
| `CONTENT_SHORT_BASE_URL` | `http://content-short-api:8080` | Base URL publik |
| `CONTENT_SHORT_APP_DIR` | repo root | Root directory aplikasi |
| `CONTENT_SHORT_STORAGE_DIR` | `<repo>/storage` | Storage directory |
| `FFMPEG_BIN` | `/usr/bin/ffmpeg` | Path ke binary FFmpeg |
| `CV_PYTHON_BIN` | venv python | Python binary untuk OpenCV |
| `VENV_DIR` | `.venv-transcript-api` | Transcript venv path |
| `SUBTITLE_AUTOCAPTIONS_PYTHON` | `<VENV_DIR>/bin/python` | Python untuk auto-captions |
| `SUBTITLE_ENABLE_SUBTITLE_API` | `true` | Enable subtitle API endpoint |
| `HOST` | `127.0.0.1` | API bind host |
| `PORT` | `8088` | API bind port |
| `NGROK_TOKEN` | — | Ngrok auth token |
| `NGROK_DOMAIN` | — | Ngrok custom domain |
| `NGROK_TARGET_PORT` | `$PORT` | Port yang di-tunnel ngrok |
| `API_KEY_YOUTUBE` | — | YouTube Data API v3 key |
| `SKIP_INSTALL` | `0` | Skip pip install saat startup |

---

## Storage Directories

Direktori ini dibuat otomatis oleh service, tetapi bisa disiapkan manual:

```bash
mkdir -p storage/{free-viral-shorts,transcripts,video,api-jobs,subtitle-jobs,trends,runtime,logs}
```

| Directory | Fungsi |
|:---|:---|
| `storage/free-viral-shorts/` | Output rendered shorts per video_id |
| `storage/transcripts/` | Transcript JSON/VTT/TXT per video_id |
| `storage/video/` | Downloaded source videos |
| `storage/api-jobs/` | API job metadata & logs |
| `storage/subtitle-jobs/` | Subtitle generation output |
| `storage/trends/` | YouTube trending data |
| `storage/runtime/` | PID file service |
| `storage/logs/` | Service log files |

---

## Assets

Pastikan asset berikut tersedia di `assets/`:

```
assets/
├── bgm/
│   └── opening_soft_bed.mp3       # BGM opening narration
├── font/
│   ├── doughsy-font/              # Font untuk thumbnail
│   ├── sheeping-cats-font/        # Font alternatif
│   └── thumbnail-title/           # Font judul thumbnail
├── thumbnail/                     # Static thumbnail per video_id
│   └── <video_id>.png
└── watermark/
    └── watermar.png               # Logo watermark
```

**Font Tambahan (untuk subtitle burn):**

Subtitle menggunakan font `Montserrat ExtraBold` / `Montserrat Black`. Install secara system-wide:

```bash
# macOS
# Download dari Google Fonts, lalu buka file .ttf untuk install

# Linux
sudo apt install fonts-montserrat
# atau manual:
mkdir -p ~/.local/share/fonts
cp Montserrat-*.ttf ~/.local/share/fonts/
fc-cache -fv
```

---

## Ngrok Setup (Opsional)

Untuk menerima webhook dari n8n atau service eksternal:

```bash
# 1. Set token di .env
echo "NGROK_TOKEN=your-token" >> .env
echo "NGROK_DOMAIN=your-subdomain.ngrok-free.dev" >> .env

# 2. Jalankan ngrok
./run_ngrok.sh
```

Ngrok akan membuat config isolasi di `.local-secrets/ngrok/ngrok.yml`.

---

## Docker Deployment

### Build & Run dengan Docker Compose

```bash
# 1. Buat network yang dibutuhkan (jika belum ada)
docker network create n8n_shared_network

# 2. Build dan start
docker compose up -d --build

# 3. Cek logs
docker compose logs -f content-short-api
```

### Docker Environment Overrides

Edit `docker-compose.yml` untuk override env vars:

```yaml
environment:
  - CONTENT_SHORT_API_TOKEN=your-production-token
  - FFMPEG_BIN=/usr/bin/ffmpeg
  - CONTENT_SHORT_BASE_URL=https://your-domain.com
```

### Port Mapping

| Container Port | Host Port | Keterangan |
|:---|:---|:---|
| `8080` | `8088` | API server |

---

## Menjalankan Service

### Mode Lokal (Development)

```bash
# Terminal 1: Jalankan API server (foreground)
./run_service.sh

# Terminal 2: Jalankan ngrok tunnel (opsional)
./run_ngrok.sh
```

### Mode Background

```bash
# Start di background, tunggu health check
./run_service.sh --background

# Cek status
./run_service.sh --status

# Stop service
./run_service.sh --stop
```

### CLI Tools

| Script | Fungsi | Contoh |
|:---|:---|:---|
| `./run.sh` | Full pipeline (download → render → watermark) | `./run.sh -n 3 "https://youtu.be/VIDEO_ID"` |
| `./run_service.sh` | Start/stop API server | `./run_service.sh --background` |
| `./run_ngrok.sh` | Start ngrok tunnel | `./run_ngrok.sh` |
| `generate_content.py` | CLI unified content generator | `python generate_content.py VIDEO_ID` |
| `generate_transcribe.py` | Standalone transcription | `python generate_transcribe.py VIDEO_ID` |

### Pipeline Steps (via `run.sh`)

```
1. Download video YouTube (yt-dlp)
2. Extract transcript (youtube-transcript-api / Whisper fallback)
3. Analyze viral moments
4. Analyze visual layout (OpenCV)
5. Generate ASS subtitles
6. Render shorts (FFmpeg)
7. Apply watermark (Pillow + FFmpeg)
```

---

## Verifikasi Instalasi

### 1. Cek System Dependencies

```bash
python3 --version         # ≥ 3.11
ffmpeg -version           # cek libass support
yt-dlp --version          # latest
git --version             # ≥ 2.30
```

### 2. Cek FFmpeg libass Support

```bash
ffmpeg -filters 2>/dev/null | grep -i ass
# Harus muncul: "subtitles" dan/atau "ass"
```

### 3. Cek Python Venvs

```bash
# API venv
.venv-api/bin/python -c "import fastapi, uvicorn, cv2, edge_tts; print('API venv OK')"

# Transcript venv
.venv-transcript-api/bin/python -c "import youtube_transcript_api; print('Transcript venv OK')"
```

### 4. Cek API Health

```bash
# Start service
./run_service.sh --background

# Health check
curl -s http://127.0.0.1:8088/health | python3 -m json.tool

# Expected: {"status": "ok", "ffmpeg": true, ...}
```

### 5. Cek Docs API (Swagger)

Buka browser: `http://127.0.0.1:8088/docs`

---

## Troubleshooting

| Masalah | Solusi |
|:---|:---|
| `ffmpeg not found` | Set `FFMPEG_BIN` di `.env`. macOS: `brew install ffmpeg` |
| `Port 8088 already in use` | `./run_service.sh --stop` lalu start ulang |
| `ModuleNotFoundError: cv2` | Aktifkan `.venv-api` lalu `pip install opencv-python-headless` |
| `Subtitle burn gagal (no libass)` | Install FFmpeg yang support libass. macOS: `brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libass` |
| `yt-dlp: command not found` | Install: `pip install yt-dlp` atau download binary |
| `Whisper transcription timeout` | Cek GPU availability, atau gunakan model `small` |
| `ngrok: command not found` | Install ngrok: `brew install ngrok/ngrok/ngrok` (macOS) |
| `Permission denied: run_service.sh` | `chmod +x run_service.sh run_ngrok.sh run.sh tools/**/*.sh` |
| Docker: `n8n_shared_network not found` | `docker network create n8n_shared_network` |
| `google-auth` error | Pastikan `client_secret_*.json` dan `token.json` tersedia |

---

## Google Cloud Credentials (Opsional)

Untuk fitur YouTube upload dan Google Drive:

1. Buat project di [Google Cloud Console](https://console.cloud.google.com/)
2. Enable YouTube Data API v3 dan Google Drive API
3. Buat OAuth 2.0 Client ID (Desktop Application)
4. Download `client_secret_*.json` ke root proyek
5. Jalankan pertama kali untuk generate `token.json`:

```bash
source .venv-api/bin/activate
python youtube_upload_direct.py --help
```

> **PENTING**: File `client_secret_*.json` dan `token.json` sudah termasuk di `.gitignore`. Jangan commit ke repository.

---

## Struktur Proyek

```
content-short/
├── api_server.py              # FastAPI main server
├── subtitle_service/          # Subtitle generation engine
│   ├── package_engine.py      # Engine orchestrator
│   ├── autocaptions_adapter.py
│   ├── whisperx_adapter.py
│   ├── ffmpeg_adapter.py
│   ├── config.py
│   └── ...
├── scripts/                   # Python CLI utilities
│   ├── generate_subtitle.py
│   ├── opening_narrator.py
│   ├── watermark_generator.py
│   ├── auto_thumbnail.py
│   └── visual_layout_analyzer.py
├── tools/                     # Shell scripts
│   ├── service/               # Service management
│   │   ├── run.sh             # Full pipeline
│   │   ├── run_service.sh     # API server
│   │   └── run_ngrok.sh       # Ngrok tunnel
│   ├── youtube/               # YouTube download/upload
│   │   ├── download_youtube_hd.sh
│   │   ├── transcribe_youtube.sh
│   │   └── upload_youtube_shorts.sh
│   ├── media/                 # Media processing
│   │   ├── free_viral_shorts.sh
│   │   └── watermark_shorts.sh
│   ├── audio/                 # Audio transcription
│   │   └── transcribe_audio_whisper.sh
│   └── youtube_trending/      # Trending video fetcher
├── external_packages/         # Vendored packages
│   └── auto-captions/
├── config/                    # Configuration files
├── assets/                    # Fonts, BGM, watermarks
├── storage/                   # Runtime data (gitignored)
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container build
├── docker-compose.yml         # Container orchestration
├── .env                       # Environment variables (gitignored)
└── .gitignore
```
