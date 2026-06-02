# Project Cleansing Plan: Fokus `CLI_GUIDE.md`

## Tujuan

Membersihkan project `content-short` agar hanya menyisakan source, asset, dan dokumentasi yang berhubungan langsung dengan workflow di `CLI_GUIDE.md`.

Prinsipnya:

1. `KEEP`: disebut langsung di `CLI_GUIDE.md`, atau dipanggil oleh script yang disebut di guide.
2. `REMOVE`: cache, hasil generated, duplikat, eksperimen, dashboard, atau fitur yang tidak masuk guide.
3. `ARCHIVE/SECRET`: file masih berguna secara lokal tetapi tidak cocok disimpan sebagai source project bersih.
4. Jangan hapus `.git` kecuali targetnya adalah membuat bundle/export tanpa histori Git.

## Ringkasan Workflow yang Dipertahankan

`CLI_GUIDE.md` mencakup workflow ini:

- Full pipeline: `run.sh`
- Render short tanpa watermark: `free_viral_shorts.sh`
- Download video: `download_youtube_hd.sh`
- Ambil transcript: `transcribe_youtube.sh`
- Watermark: `watermark_shorts.sh`
- Upload YouTube Shorts: `upload_youtube_shorts.sh`
- Dokumentasi uploader: `youtube_uploader_env_guide.md`

## File/Folders yang Dipertahankan

### Dokumentasi utama

| Path | Alasan |
|---|---|
| `CLI_GUIDE.md` | Panduan utama yang jadi acuan cleansing |
| `youtube_uploader_env_guide.md` | Direferensikan langsung oleh `CLI_GUIDE.md` untuk upload |
| `CLEANSE_PLAN.md` | Plan cleansing ini |

### CLI script utama

| Path | Alasan |
|---|---|
| `run.sh` | Full auto pipeline di `CLI_GUIDE.md` |
| `free_viral_shorts.sh` | Core renderer/analyzer di `CLI_GUIDE.md` |
| `download_youtube_hd.sh` | Downloader di `CLI_GUIDE.md` |
| `transcribe_youtube.sh` | Transcript extractor di `CLI_GUIDE.md` |
| `watermark_shorts.sh` | Watermark CLI di `CLI_GUIDE.md` |
| `upload_youtube_shorts.sh` | Upload CLI di `CLI_GUIDE.md` |

### Python dependency dari CLI utama

| Path | Dipakai oleh |
|---|---|
| `scripts/visual_layout_analyzer.py` | `free_viral_shorts.sh` |
| `scripts/subtitle_ass_generator.py` | `free_viral_shorts.sh` |
| `scripts/watermark_generator.py` | `watermark_shorts.sh` |
| `youtube_upload_direct.py` | `upload_youtube_shorts.sh` |

### Optional dependency yang masih dipanggil script utama

File ini tidak ditonjolkan di `CLI_GUIDE.md`, tetapi masih dipanggil oleh `free_viral_shorts.sh` jika opsi opening/thumbnail digunakan.

| Path | Alasan |
|---|---|
| `scripts/opening_narrator.py` | Optional opening narration path di `free_viral_shorts.sh` |
| `scripts/auto_thumbnail.py` | Di-import oleh `opening_narrator.py` |
| `assets/bgm/opening_soft_bed.mp3` | Default/asset pendukung opening BGM |
| `assets/font/thumbnail-title/` | Font thumbnail opening |

Jika ingin benar-benar minimal sesuai `CLI_GUIDE.md` saja, opsi opening bisa dihapus dari `run.sh` dan `free_viral_shorts.sh`, lalu file optional di atas bisa ikut dibuang. Itu perubahan kode, bukan sekadar cleansing file.

### Assets yang diperlukan

| Path | Alasan |
|---|---|
| `assets/watermark/` | Lokasi watermark image/logo sesuai guide |
| `assets/font/doughsy-font/Doughsy-zrBq4.ttf` | Default font watermark |
| `assets/font/doughsy-font/info.txt` | Metadata font |
| `assets/font/doughsy-font/misc/` | License font |

Catatan: `assets/font/sheeping-cats-font/` hanya dipertahankan jika masih dipakai manual untuk subtitle/watermark. Jika tidak, bisa masuk kandidat hapus.

### Folder output/cache

`CLI_GUIDE.md` banyak menyebut folder ini, tetapi isinya adalah hasil generated/cache. Untuk project bersih, folder boleh disisakan kosong dengan `.gitkeep`.

| Path | Keputusan |
|---|---|
| `storage/free-viral-shorts/` | Sisakan folder kosong atau hapus semua isi generated |
| `storage/transcripts/` | Sisakan folder kosong atau hapus semua isi cache |
| `storage/video/` | Sisakan folder kosong atau hapus semua isi video cache |

## File/Folders yang Dihapus

### Cache dan generated output

| Path | Alasan |
|---|---|
| `storage/free-viral-shorts/*` | Output render, bisa dibuat ulang |
| `storage/transcripts/*` | Cache transcript, bisa dibuat ulang |
| `storage/video/*` | Cache video, bisa dibuat ulang |
| `storage/trends/` | Tidak dipakai workflow `CLI_GUIDE.md` |
| `__pycache__/` | Python bytecode cache |
| `scripts/__pycache__/` | Python bytecode cache |
| `.DS_Store` | File sistem macOS |
| `storage/.DS_Store` | File sistem macOS |

### Duplikat/backup script

| Path | Alasan |
|---|---|
| `scripts/visual_layout_analyzer copy.py` | Backup/duplikat |
| `scripts/visual_layout_analyzer copy 2.py` | Backup/duplikat |
| `scripts/subtitle_ass_generator_duplicate.py` | Backup/duplikat |

### Fitur di luar `CLI_GUIDE.md`

| Path | Alasan |
|---|---|
| `auto_trend_shorts.sh` | Workflow trend crawler tidak ada di `CLI_GUIDE.md` |
| `scripts/youtube_trend_discover.py` | Hanya dipakai `auto_trend_shorts.sh` |
| `config/youtube_trend_keywords.json` | Hanya untuk trend crawler |
| `youtube_trend_crawler_guide.md` | Dokumentasi trend crawler |
| `upload_social_video.sh` | Upload multi-platform tidak ada di `CLI_GUIDE.md` |
| `upload_platform_env_guide.md` | Dokumentasi upload platform lain |
| `viral_shorts_generator.sh` | Legacy/alternate script, tidak ada di guide |
| `render_opening_narration.sh` | Standalone helper, tidak ada di guide |
| `clip_cli_dashboard_executable/` | Dashboard executable, tidak ada di guide |
| `clip_cli_dashboard_executable.zip` | Arsip dashboard executable |
| `first-frontend-ShortForge.md` | Brief frontend, bukan CLI guide |
| `AUDIT_ISSUE25.md` | Audit dashboard/API, bukan CLI guide |
| `auto-thumbnail.md` | Prompt/rules thumbnail, hanya simpan jika optional opening tetap dipertahankan sebagai fitur aktif |

### Dokumentasi duplikat

Isi berikut sudah dicakup `CLI_GUIDE.md`, jadi bisa dihapus setelah memastikan tidak ada detail unik yang masih dibutuhkan.

| Path | Alasan |
|---|---|
| `download_youtube_hd.md` | Duplikat bagian download |
| `free_viral_shorts.md` | Duplikat bagian render/analyze |
| `transcribe_youtube.md` | Duplikat bagian transcript |
| `TODO.md` | Tidak diperlukan untuk bundle CLI bersih |

### Environment lokal dan secret

| Path | Keputusan |
|---|---|
| `.venv-transcript-api/` | Hapus dari source; `transcribe_youtube.sh` bisa membuat ulang |
| `.blackbox/` | Hapus jika bukan bagian workflow CLI |
| `.blackboxrules` | Hapus jika bukan bagian workflow CLI |
| `token.json` | Jangan commit. Simpan lokal sebagai secret karena `youtube_upload_direct.py` default membutuhkannya untuk upload |
| `sample_request.json` | Hapus jika tidak dipakai upload metadata lokal |

## Struktur Akhir yang Disarankan

```txt
content-short/
  CLI_GUIDE.md
  CLEANSE_PLAN.md
  youtube_uploader_env_guide.md
  run.sh
  free_viral_shorts.sh
  download_youtube_hd.sh
  transcribe_youtube.sh
  watermark_shorts.sh
  upload_youtube_shorts.sh
  youtube_upload_direct.py
  scripts/
    visual_layout_analyzer.py
    subtitle_ass_generator.py
    watermark_generator.py
    opening_narrator.py
    auto_thumbnail.py
  assets/
    watermark/
    bgm/opening_soft_bed.mp3
    font/
      doughsy-font/
      thumbnail-title/
  storage/
    free-viral-shorts/.gitkeep
    transcripts/.gitkeep
    video/.gitkeep
```

## Eksekusi Aman

### 1. Audit ukuran sebelum hapus

```bash
du -sh * .[^.]* 2>/dev/null
```

### 2. Buat branch khusus

```bash
git checkout -b cleanse-cli-guide
```

### 3. Pindahkan secret dan file lokal

```bash
mkdir -p .local-secrets
mv token.json .local-secrets/token.json
```

Catatan: setelah dipindah, upload direct perlu dijalankan dari folder yang punya `token.json`, atau code/script perlu ditambah opsi/env untuk path token. Alternatif lebih sederhana: tetap simpan `token.json` di root lokal tetapi masukkan ke `.gitignore`.

### 4. Hapus cache/generated output

```bash
rm -rf \
  storage/free-viral-shorts/* \
  storage/transcripts/* \
  storage/video/* \
  storage/trends \
  __pycache__ \
  scripts/__pycache__ \
  .DS_Store \
  storage/.DS_Store
```

### 5. Sisakan folder output kosong

```bash
mkdir -p storage/free-viral-shorts storage/transcripts storage/video
touch storage/free-viral-shorts/.gitkeep storage/transcripts/.gitkeep storage/video/.gitkeep
```

### 6. Hapus file di luar scope

```bash
rm -rf \
  clip_cli_dashboard_executable \
  clip_cli_dashboard_executable.zip \
  .venv-transcript-api \
  .blackbox \
  .blackboxrules

rm -f \
  "scripts/visual_layout_analyzer copy.py" \
  "scripts/visual_layout_analyzer copy 2.py" \
  scripts/subtitle_ass_generator_duplicate.py \
  auto_trend_shorts.sh \
  upload_social_video.sh \
  viral_shorts_generator.sh \
  render_opening_narration.sh \
  scripts/youtube_trend_discover.py \
  config/youtube_trend_keywords.json \
  youtube_trend_crawler_guide.md \
  upload_platform_env_guide.md \
  first-frontend-ShortForge.md \
  AUDIT_ISSUE25.md \
  download_youtube_hd.md \
  free_viral_shorts.md \
  transcribe_youtube.md \
  TODO.md \
  sample_request.json
```

### 7. Tambahkan `.gitignore`

```gitignore
.DS_Store
__pycache__/
*.pyc
.venv*/
token.json
.local-secrets/
storage/free-viral-shorts/*
storage/transcripts/*
storage/video/*
!storage/free-viral-shorts/.gitkeep
!storage/transcripts/.gitkeep
!storage/video/.gitkeep
```

### 8. Validasi setelah cleansing

```bash
bash -n run.sh
bash -n free_viral_shorts.sh
bash -n download_youtube_hd.sh
bash -n transcribe_youtube.sh
bash -n watermark_shorts.sh
bash -n upload_youtube_shorts.sh

./download_youtube_hd.sh --help
./transcribe_youtube.sh --help
./free_viral_shorts.sh --help
./watermark_shorts.sh --help
./upload_youtube_shorts.sh --help
```

## Estimasi Dampak

Ukuran saat audit:

- `storage/`: sekitar 632 MB
- `.venv-transcript-api/`: sekitar 29 MB
- `assets/`: sekitar 2.8 MB
- `scripts/`: sekitar 1.1 MB
- `clip_cli_dashboard_executable/`: sekitar 212 KB

Setelah cleansing, project source seharusnya tinggal beberapa MB plus asset font/BGM. Cache runtime akan dibuat ulang saat CLI dijalankan.

## Catatan Risiko

- Jangan hapus `.git` untuk cleansing normal. Hapus `.git` hanya jika ingin membuat copy project tanpa histori.
- Jangan commit `token.json`. Tetapi upload direct saat ini default mencari `token.json`, jadi perlu tetap tersedia secara lokal atau script perlu dimodifikasi agar menerima env/path token.
- Jika optional opening/thumbnail ingin dibuang juga, lakukan sebagai perubahan kode terpisah: hapus opsi opening dari `run.sh` dan `free_viral_shorts.sh`, lalu hapus `scripts/opening_narrator.py`, `scripts/auto_thumbnail.py`, `assets/bgm/`, dan `assets/font/thumbnail-title/`.
