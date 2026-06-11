# Content Short Windows Installation Plan

Panduan ini menjelaskan instalasi proyek Content Short di Windows melalui WSL2 Ubuntu.
Gunakan WSL2, bukan native CMD/PowerShell, karena proyek ini memakai bash scripts,
path Linux, FFmpeg/libass, dan virtual environment Linux.

## Target Platform

- Windows 10/11 dengan WSL2
- Ubuntu 22.04 di WSL
- Python 3.11+
- FFmpeg dengan dukungan libass/subtitles
- yt-dlp latest
- Git dan curl

## 1. Install WSL2 Ubuntu

Jalankan PowerShell sebagai Administrator:

```powershell
wsl --install -d Ubuntu-22.04
```

Restart Windows jika diminta, lalu buka Ubuntu dari Start Menu atau jalankan:

```powershell
wsl
```

## 2. Clone Repository di Filesystem WSL

Simpan repo di filesystem Linux WSL, bukan di `/mnt/c`, agar file permission,
venv, dan bash scripts lebih stabil.

```bash
mkdir -p ~/projects
cd ~/projects
git clone <REPO_URL> content-short
cd content-short
```

Jika repo sudah ada, cukup masuk ke folder repo:

```bash
cd ~/projects/content-short
```

## 3. Install System Dependencies

```bash
sudo apt update
sudo apt install -y \
  python3.11 python3.11-venv python3.11-dev \
  ffmpeg git curl wget build-essential libass-dev \
  fonts-montserrat
```

Install `yt-dlp` latest:

```bash
sudo curl -sL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
  -o /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp
```

## 4. Setup Python Virtual Environments

API server venv:

```bash
python3.11 -m venv .venv-api
source .venv-api/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
deactivate
```

Transcript/subtitle venv:

```bash
python3.11 -m venv .venv-transcript-api
source .venv-transcript-api/bin/activate
pip install --upgrade pip wheel "setuptools<82"
pip install youtube-transcript-api openai-whisper
deactivate
```

## 5. Setup External Packages

```bash
mkdir -p external_packages
cd external_packages

if [ ! -d auto-captions ]; then
  git clone https://github.com/nikhil-reddy05/auto-captions.git
fi

cd auto-captions
source ../../.venv-transcript-api/bin/activate
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
deactivate

cd ../..
```

## 6. Create Environment File

Buat `.env` di root repo. Jangan commit file ini.

```dotenv
CONTENT_SHORT_API_TOKEN=change-me-local
CONTENT_SHORT_BASE_URL=http://127.0.0.1:8088
HOST=127.0.0.1
PORT=8088

FFMPEG_BIN=/usr/bin/ffmpeg
VENV_DIR=.venv-transcript-api
SUBTITLE_AUTOCAPTIONS_PYTHON=.venv-transcript-api/bin/python
SUBTITLE_ENABLE_SUBTITLE_API=true

WEBHOOK_URL=http://127.0.0.1:8088
```

Tambahkan variabel opsional jika dibutuhkan:

```dotenv
API_KEY_YOUTUBE=your-youtube-data-api-key
NGROK_TOKEN=your-ngrok-token
NGROK_DOMAIN=your-domain.ngrok-free.dev
NGROK_TARGET_PORT=8088
```

## 7. Prepare Runtime Directories and Scripts

```bash
mkdir -p storage/{free-viral-shorts,transcripts,video,api-jobs,subtitle-jobs,trends,runtime,logs}
chmod +x run.sh run_service.sh run_ngrok.sh tools/**/*.sh
```

## 8. Run the Service

Start API server:

```bash
./run_service.sh --background
```

Health check dari WSL:

```bash
curl -s http://127.0.0.1:8088/health | python3 -m json.tool
```

Buka Swagger dari browser Windows:

```text
http://127.0.0.1:8088/docs
```

## 9. Optional Ngrok Setup

Pastikan `.env` berisi `NGROK_TOKEN`. Lalu jalankan:

```bash
./run_ngrok.sh
```

Ngrok config lokal akan dibuat di `.local-secrets/ngrok/ngrok.yml`.

## 10. Optional Google Upload Setup

Untuk upload YouTube/Google Drive:

1. Enable YouTube Data API v3 dan Google Drive API di Google Cloud Console.
2. Buat OAuth 2.0 Client ID tipe Desktop Application.
3. Simpan `client_secret_*.json` di root repo.
4. Jalankan:

```bash
source .venv-api/bin/activate
python youtube_upload_direct.py --help
deactivate
```

Pastikan `client_secret_*.json` dan `token.json` tidak di-commit.

## Validation Checklist

Jalankan semua command berikut:

```bash
python3 --version
ffmpeg -version
ffmpeg -filters 2>/dev/null | grep -i ass
yt-dlp --version
git --version
.venv-api/bin/python -c "import fastapi, uvicorn, cv2, edge_tts; print('API venv OK')"
.venv-transcript-api/bin/python -c "import youtube_transcript_api, whisper; print('Transcript venv OK')"
curl -s http://127.0.0.1:8088/health | python3 -m json.tool
```

Instalasi dianggap berhasil jika:

- Python minimal 3.11 tersedia.
- FFmpeg tersedia dan filter `ass` atau `subtitles` muncul.
- `yt-dlp` tersedia.
- API venv bisa import dependency utama.
- Transcript venv bisa import `youtube_transcript_api` dan `whisper`.
- Endpoint `/health` aktif.
- Swagger bisa dibuka di `http://127.0.0.1:8088/docs`.

## Troubleshooting

| Masalah | Solusi |
|:---|:---|
| `ffmpeg not found` | Pastikan `FFMPEG_BIN=/usr/bin/ffmpeg` di `.env` dan `sudo apt install ffmpeg` sudah dijalankan. |
| Subtitle burn gagal | Cek `ffmpeg -filters 2>/dev/null | grep -i ass`; pastikan FFmpeg punya filter `ass` atau `subtitles`. |
| `yt-dlp: command not found` | Install ulang binary `yt-dlp` ke `/usr/local/bin/yt-dlp`. |
| `ModuleNotFoundError: cv2` | Aktifkan `.venv-api`, lalu jalankan `pip install -r requirements.txt`. |
| `ModuleNotFoundError: whisper` | Aktifkan `.venv-transcript-api`, lalu jalankan `pip install openai-whisper`. |
| Port 8088 sudah dipakai | Jalankan `./run_service.sh --stop`, lalu start ulang. |
| Script permission denied | Jalankan `chmod +x run.sh run_service.sh run_ngrok.sh tools/**/*.sh`. |
| Browser Windows tidak bisa membuka API | Pastikan service bind ke `HOST=127.0.0.1` dan WSL masih berjalan. |

## Notes

- Jangan jalankan pipeline dari native Windows CMD/PowerShell.
- Jangan simpan repo di `/mnt/c` kecuali ada alasan khusus.
- Jangan commit `.env`, token, credential, atau output `storage/`.
- Docker di Windows boleh dipakai sebagai opsi lanjutan, tetapi jalur utama proyek ini adalah WSL2.
