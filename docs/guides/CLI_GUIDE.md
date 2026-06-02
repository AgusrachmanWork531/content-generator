# Content Short CLI Guide

Panduan menjalankan semua CLI di folder `content-short`.

## Prasyarat

Jalankan dari folder:

```bash
cd /Users/agusrachman/Documents/Codex/content-short
```

Tools utama:

```bash
yt-dlp --version
/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -version
python3 --version
```

`ffmpeg-full` dipakai agar subtitle `.ass` bisa dibakar ke video.

## Full Auto

Download video, ambil transcript, cari moment viral, buat subtitle, render short, lalu apply watermark:

```bash
./run.sh "https://youtu.be/VIDEO_ID"
```

Contoh 3 short end-to-end:

```bash
./run.sh -n 3 "https://youtu.be/VIDEO_ID"
```

Pakai cache transcript/video dan lanjut sampai watermark:

```bash
./run.sh --skip-download --skip-transcript -n 3 VIDEO_ID
```

Tanpa watermark:

```bash
./run.sh --no-watermark -n 3 VIDEO_ID
```

Output final watermark ada di:

```txt
storage/free-viral-shorts/VIDEO_ID/watermarked/
```

## Render Tanpa Watermark

Download video, ambil transcript, cari moment viral, buat subtitle, dan render short tanpa step watermark:

```bash
./free_viral_shorts.sh "https://youtu.be/VIDEO_ID"
```

Contoh 3 short:

```bash
./free_viral_shorts.sh -n 3 "https://youtu.be/VIDEO_ID"
```

Output:

```txt
storage/free-viral-shorts/VIDEO_ID/
  loading_state.json
  loading_history.jsonl
  result.json
  moments.md
  crop_plan.json
  clips/clip_01.srt
  clips/clip_01.ass
  shorts/short_01.mp4
```

## Pakai Cache

Jika transcript dan video sudah ada:

```bash
./free_viral_shorts.sh --skip-download --skip-transcript -n 3 VIDEO_ID
```

Jika hanya video sudah ada, tapi transcript mau dibuat ulang:

```bash
./free_viral_shorts.sh --skip-download -n 3 VIDEO_ID
```

Jika hanya transcript sudah ada, tapi video mau didownload ulang:

```bash
./free_viral_shorts.sh --skip-transcript -n 3 VIDEO_ID
```

## Analyze Only

Hanya cari moment viral, tanpa render video:

```bash
./free_viral_shorts.sh --skip-download --skip-transcript --skip-render -n 1 VIDEO_ID
```

Atau shortcut:

```bash
./free_viral_shorts.sh --analyze-only -n 1 VIDEO_ID
```

Catatan: `--skip-render` memang berhenti setelah `moments.md` dan `result.json`.

## Render Full dari Cache

Jika sebelumnya hanya analyze, lanjutkan full render dari cache:

```bash
./free_viral_shorts.sh --skip-download --skip-transcript -n 1 VIDEO_ID
```

Jangan pakai `--skip-render` kalau ingin output `.mp4`.

## Download Video Saja

Download HD ke `storage/video`:

```bash
./download_youtube_hd.sh "https://youtu.be/VIDEO_ID"
```

Pilih kualitas:

```bash
./download_youtube_hd.sh -q 720 "https://youtu.be/VIDEO_ID"
./download_youtube_hd.sh -q 1080 "https://youtu.be/VIDEO_ID"
./download_youtube_hd.sh -q best "https://youtu.be/VIDEO_ID"
```

Download subtitle juga:

```bash
./download_youtube_hd.sh --subs "https://youtu.be/VIDEO_ID"
```

Untuk video yang butuh sesi browser:

```bash
./download_youtube_hd.sh --cookies-from-browser chrome "https://youtu.be/VIDEO_ID"
```

## Transcript Saja

Ambil transcript ke `storage/transcripts/VIDEO_ID`:

```bash
./transcribe_youtube.sh "https://youtu.be/VIDEO_ID"
```

Prioritas bahasa:

```bash
./transcribe_youtube.sh -l id,en "https://youtu.be/VIDEO_ID"
```

Pilih caption auto-generated:

```bash
./transcribe_youtube.sh --prefer generated "https://youtu.be/VIDEO_ID"
```

Cek caption tersedia:

```bash
./transcribe_youtube.sh --list "https://youtu.be/VIDEO_ID"
```

Jika `youtube-transcript-api` kena IP block, script otomatis mencoba fallback:

```txt
youtube-transcript-api -> yt-dlp subtitle fallback -> local subtitle cache
```

## Loading State

Saat `free_viral_shorts.sh` berjalan, progress ditulis ke:

```txt
storage/free-viral-shorts/VIDEO_ID/loading_state.json
storage/free-viral-shorts/VIDEO_ID/loading_history.jsonl
```

Lihat status terakhir:

```bash
cat storage/free-viral-shorts/VIDEO_ID/loading_state.json
```

Pantau history:

```bash
tail -f storage/free-viral-shorts/VIDEO_ID/loading_history.jsonl
```

Step normal:

```txt
Starting pipeline
Preparing transcript
Preparing source video
Finding viral moments
Planning camera layout
Generating subtitles
Rendering shorts
Completed
```

## Watermark

Watermark dijalankan setelah video short selesai dirender.

Lokasi standar untuk image/logo watermark:

```txt
assets/watermark/
```

Contoh:

```txt
assets/watermark/watermar.png
assets/watermark/logo.png
assets/watermark/logo-transparent.png
```

Format yang disarankan:

```txt
PNG transparan
Rasio bebas
Tinggi logo cukup 256-512px agar tajam saat diskalakan
```

Tambahkan watermark text default:

```bash
./watermark_shorts.sh VIDEO_ID
```

Default watermark memakai:

```txt
Text: @KilasanVideo
Mode: text
Position: center_15_top
Y: 15% dari atas frame
Font: assets/font/sheeping-cats-font/SheepingCatsStraight-lrlZ.ttf
```

Tambahkan watermark text custom:

```bash
./watermark_shorts.sh VIDEO_ID --text "@YourChannel" --mode text --position center_15_top
```

Pakai font custom:

```bash
./watermark_shorts.sh VIDEO_ID --text "@YourChannel" --font assets/font/sheeping-cats-font/SheepingCatsStraight-lrlZ.ttf --mode text --position center_15_top
```

Tambahkan watermark logo/image:

```bash
./watermark_shorts.sh VIDEO_ID --logo assets/watermark/logo.png --mode logo
```

Mode otomatis, logo + text dalam badge:

```bash
./watermark_shorts.sh VIDEO_ID --logo assets/watermark/logo.png --text "@YourChannel" --mode auto
```

Pilih posisi manual:

```bash
./watermark_shorts.sh VIDEO_ID --text "@YourChannel" --position top_right
./watermark_shorts.sh VIDEO_ID --text "@YourChannel" --position top_left
./watermark_shorts.sh VIDEO_ID --text "@YourChannel" --position center_15_top
./watermark_shorts.sh VIDEO_ID --text "@YourChannel" --position center
./watermark_shorts.sh VIDEO_ID --text "@YourChannel" --position center_top
./watermark_shorts.sh VIDEO_ID --mode logo --position center_left
./watermark_shorts.sh VIDEO_ID --mode logo --position center_right
./watermark_shorts.sh VIDEO_ID --mode logo --position center_bottom
```

Dry run untuk cek plan tanpa render:

```bash
./watermark_shorts.sh VIDEO_ID --dry-run
```

Output watermark:

```txt
storage/free-viral-shorts/VIDEO_ID/watermark_plan.json
storage/free-viral-shorts/VIDEO_ID/watermarked/short_01_wm.mp4
```

Setelah watermark selesai, `result.json` akan di-update dengan:

```txt
watermark_plan
watermarked_file
final_video_file
```

## Bersihkan Result

Hapus hasil short untuk satu video:

```bash
rm -rf storage/free-viral-shorts/VIDEO_ID
```

Hapus transcript cache:

```bash
rm -rf storage/transcripts/VIDEO_ID
```

Hapus semua hasil generated dan file/folder lokal yang tidak diperlukan untuk flow utama proyek:

```bash
rm -rf \
  storage/free-viral-shorts \
  storage/transcripts \
  storage/video \
  .local-cache \
  __pycache__ \
  scripts/__pycache__ \
  .DS_Store \
  storage/.DS_Store
```

Buat ulang folder runtime agar command berikutnya tetap bisa jalan:

```bash
mkdir -p \
  storage/free-viral-shorts \
  storage/transcripts \
  storage/video \
  storage/api-jobs
```

Catatan: command di atas hanya menghapus output/cache runtime. Jangan hapus file source flow utama seperti `run.sh`, `free_viral_shorts.sh`, `download_youtube_hd.sh`, `transcribe_youtube.sh`, `watermark_shorts.sh`, `upload_youtube_shorts.sh`, `api_server.py`, `scripts/`, `assets/`, `.env`, dan dokumentasi yang masih dipakai.

Jika ingin membersihkan isi storage tetapi tetap mempertahankan foldernya:

```bash
rm -rf \
  storage/free-viral-shorts/* \
  storage/transcripts/* \
  storage/video/* \
  storage/api-jobs/*
```

## Troubleshooting

Jika command langsung selesai:

```txt
Kemungkinan memakai --skip-render.
```

Gunakan command ini untuk render:

```bash
./free_viral_shorts.sh --skip-download --skip-transcript -n 1 VIDEO_ID
```

Jika berhenti lama di `Planning camera layout`:

```txt
Script sedang sampling frame dengan OpenCV untuk crop/split-frame.
```

Jika transcript gagal karena IP block:

```bash
./transcribe_youtube.sh -l id,en "https://youtu.be/VIDEO_ID"
```

Jika subtitle tidak muncul di video:

```bash
/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -hide_banner -filters | grep -E ' ass | subtitles '
```

Harus muncul:

```txt
ass
subtitles
```

## Upload ke YouTube (Shorts)

Catatan environment uploader (Python venv / OAuth): lihat juga `youtube_uploader_env_guide.md`.


Script: `upload_youtube_shorts.sh`

Fungsi: mengupload file short yang sudah dirender oleh pipeline `free_viral_shorts.sh` ke YouTube.

### Prasyarat
- Shorts sudah ada di folder:

```txt
storage/free-viral-shorts/VIDEO_ID/shorts/short_01.mp4
storage/free-viral-shorts/<VIDEO_ID>/shorts/short_02.mp4
...
```

- (Opsional tapi direkomendasikan) file `moments.md` juga ada di:

```txt
storage/free-viral-shorts/<VIDEO_ID>/moments.md
```

Agar judul/“hook” per-clip bisa diambil otomatis dari `moments.md`.

- Script uploader menggunakan implementasi dari project `download-clip`, default path:

```txt
/Users/agusrachman/Documents/Docker/n8n/download-clip
```

### Cara menjalankan
Jalankan dari folder:

```bash
cd /Users/agusrachman/Documents/Codex/content-short
```

Command:

```bash
./upload_youtube_shorts.sh -r <VIDEO_ID | run_dir> [options]
```

- `-r/--run`:
  - bisa berupa `VIDEO_ID` (mis. `fVWowlAW928`)
  - atau path “run_dir” yang berisi `result.json`.

### Options
```txt
--base-dir DIR                 Default: storage/free-viral-shorts
--title TEXT                   Title (default untuk semua short jika tidak ada override)
--description TEXT             Description (akan append #Shorts jika missing di uploader)
--tags "a,b,c"                Tags (comma-separated). Jika kosong, default: ['Shorts']
--privacy public|unlisted|private   Default: unlisted
--thumbnail FILE              Optional thumbnail path
--dry-run                      Tidak upload, hanya tampilkan rencana upload
-h, --help
```

### Contoh
Upload 1 run berdasarkan `VIDEO_ID`:

```bash
./upload_youtube_shorts.sh -r fVWowlAW928 \
  --privacy unlisted
```

Upload dengan metadata custom (aplikasi ke semua short):

```bash
DOWNLOAD_CLIP_VENV_PY="/Users/agusrachman/Documents/Docker/n8n/.venv/bin/python" ./upload_youtube_shorts.sh -r fVWowlAW928 \
  --title "Judul Channel" \
  --description "Deskripsi" \
  --tags "shorts,indonesia" \
  --privacy unlisted
```

Dry-run (cek metadata & file yang akan diupload):

```bash
./upload_youtube_shorts.sh -r fVWowlAW928 --dry-run
```

Upload menggunakan path run_dir langsung:

```bash
./upload_youtube_shorts.sh -r storage/free-viral-shorts/fVWowlAW928
```

### Cara script memilih judul/description/tags
- Looping semua file:

```txt
<run_dir>/shorts/short_*.mp4
```

- Metadata:
  - Jika `--title/--description/--tags/--privacy/--thumbnail` diisi, nilai itu jadi default untuk semua clip.
  - Jika `--title` tidak diisi, script ambil best-effort per-clip dari `moments.md` (bagian `- Title:`).
  - Jika `--description` tidak diisi, script best-effort menyusun description dari `moments.md`:
    - `Hook:` dan `Why viral:`.
  - Tags default:
    - jika `--tags` kosong/tidak diisi: `['Shorts']`.

- Thumbnail:
  - jika `--thumbnail` ada, akan dipasang ke setiap upload.

### Troubleshooting
- `No shorts found in .../shorts`:
  - Pastikan file `short_01.mp4`, `short_02.mp4`, dst sudah ada.

- `Cannot resolve run dir ... result.json ...`:
  - `-r` harus berupa `VIDEO_ID` yang ada di `--base-dir`, atau path yang benar-benar mengandung `result.json`.

- Upload gagal terkait import uploader:
  - Pastikan folder `download-clip` ada dan module `app.services.youtube_upload` tersedia.
  - (Kalau diperlukan) set env `DOWNLOAD_CLIP_DIR` atau gunakan default sesuai script.

## Command Cepat

Full:

```bash
./free_viral_shorts.sh -n 3 "https://youtu.be/VIDEO_ID"
```

Cepat dari cache:

```bash
./free_viral_shorts.sh --skip-download --skip-transcript -n 3 VIDEO_ID
```

Analyze saja:

```bash
./free_viral_shorts.sh --skip-download --skip-transcript --skip-render -n 3 VIDEO_ID
```

Render satu clip untuk testing:

```bash
./free_viral_shorts.sh --skip-download --skip-transcript -n 1 VIDEO_ID
```

Watermark setelah render:

```bash
./watermark_shorts.sh VIDEO_ID
```

## Local ngrok Webhook URL

Jika ingin expose API ke internet tanpa menambahkan service ngrok di Docker:

### Prasyarat

- Jalankan ngrok dari host machine (bukan dari container).
- API lokal tetap bisa diakses via `localhost:8088`.

### Environment Variables

Contoh setup dengan static ngrok domain:

```bash
export WEBHOOK_URL="https://wirelike-long-starkly.ngrok-free.dev"
export CONTENT_SHORT_BASE_URL="$WEBHOOK_URL"
export CONTENT_SHORT_API_TOKEN="change-me"
```

Atau cukup `WEBHOOK_URL` saja:

```bash
export WEBHOOK_URL="https://wirelike-long-starkly.ngrok-free.dev"
export CONTENT_SHORT_API_TOKEN="change-me"
```

### Jalankan ngrok

Dari host machine:

```bash
ngrok http 8088 --url=https://wirelike-long-starkly.ngrok-free.dev
```

### Test Health

```bash
curl -i "https://wirelike-long-starkly.ngrok-free.dev/health"
```

### Test Generate Job

```bash
curl -i -X POST "https://wirelike-long-starkly.ngrok-free.dev/jobs/generate" \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"source":"https://youtu.be/VIDEO_ID"}'
```

### Catatan

- Jika API diakses publik di internet, ganti token default `change-me` dengan token yang lebih aman.
- Jika tidak menggunakan reserved/static ngrok domain, URL ngrok berubah setiap kali service di-restart dan perlu update environment variable.

## Run API Without Docker

Jalankan API langsung dari host machine tanpa Docker.

### Prasyarat

Masuk ke folder repo:

```bash
cd /Users/agusrachman/Documents/Codex/content-short
```

### Setup Environment

Buat venv dan install dependencies:

```bash
python3 -m venv .venv-api
source .venv-api/bin/activate
pip install -r requirements.txt
```

Set environment variables:

```bash
export CONTENT_SHORT_APP_DIR="$PWD"
export CONTENT_SHORT_STORAGE_DIR="$PWD/storage"
export CONTENT_SHORT_API_TOKEN="change-me"
export WEBHOOK_URL="https://wirelike-long-starkly.ngrok-free.dev"
export CONTENT_SHORT_BASE_URL="$WEBHOOK_URL"
export FFMPEG_BIN="$(which ffmpeg)"
export CV_PYTHON_BIN="$(which python3)"
export VENV_DIR="$PWD/.venv-transcript-api"
```

### Start API

Jalankan uvicorn:

```bash
uvicorn api_server:app --host 127.0.0.1 --port 8088
```

### Test Health

```bash
curl -i "http://localhost:8088/health"
```

Expected response:

```txt
HTTP/1.1 200 OK
```

### Test Generate Job

```bash
curl -i -X POST "http://localhost:8088/jobs/generate" \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"source":"https://youtu.be/VIDEO_ID"}'
```

### Optional: Expose via ngrok

Dari terminal lain, jalankan ngrok:

```bash
ngrok http 8088 --url=https://wirelike-long-starkly.ngrok-free.dev
```

Test public health:

```bash
curl -i "https://wirelike-long-starkly.ngrok-free.dev/health"
```
