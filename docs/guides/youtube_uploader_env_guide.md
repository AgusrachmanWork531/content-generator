# Youtube uploader env guide (untuk `upload_youtube_shorts.sh`)

Script `content-short/upload_youtube_shorts.sh` memakai uploader dari project:

`/Users/agusrachman/Documents/Docker/n8n/download-clip`

Supaya dependency (contoh `googleapiclient`) dan environment OAuth berjalan, Python yang dipakai **harus berasal dari venv uploader**.

## 1) Set `DOWNLOAD_CLIP_VENV_PY`

Pada sistem kamu, venv yang benar ada di:

```txt
/Users/agusrachman/Documents/Docker/n8n/download-clip/.venv/bin/python
```

Contoh menjalankan dry-run:

```bash
cd /Users/agusrachman/Documents/Codex/content-short

DOWNLOAD_CLIP_VENV_PY="/Users/agusrachman/Documents/Docker/n8n/download-clip/.venv/bin/python" \
./upload_youtube_shorts.sh -r fVWowlAW928 \
  --title "Judul Channel" \
  --description "Deskripsi" \
  --tags "shorts,indonesia" \
  --privacy unlisted \
  --dry-run
```

## 2) Kenapa harus pakai `.venv` ini?

Project `download-clip` punya `requirements.txt` yang memuat:
- `google-api-python-client` (menyediakan module `googleapiclient`)

Jika `upload_youtube_shorts.sh` memakai Python global (`python3`) atau venv lain, bisa muncul error:

```txt
ModuleNotFoundError: No module named 'googleapiclient'
```

## 3) Copy “config” yang dimaksud

Kalau yang kamu maksud adalah menyalin path python venv:
- maka pastikan `DOWNLOAD_CLIP_VENV_PY` mengarah ke `.venv/bin/python` di `download-clip`.

Jika yang kamu maksud adalah menyalin file OAuth (`client-secret.json`, `token.json`) ke project ini, itu *bukan* diperlukan oleh script ini selama dependency uploader dijalankan dengan venv yang sama.

Namun, uploader di `download-clip` tetap akan mencari file OAuth sesuai implementasi `app/services/google_auth.py` di project tersebut.

## 4) Verifikasi cepat

Verifikasi Python venv sudah benar (tanpa menjalankan upload):

```bash
/Users/agusrachman/Documents/Docker/n8n/download-clip/.venv/bin/python -c "import googleapiclient; print('googleapiclient OK')"
```

