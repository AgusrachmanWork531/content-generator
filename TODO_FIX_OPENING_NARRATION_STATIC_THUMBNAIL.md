# Plan: Use Static Asset Thumbnail for Opening Narration

## Tujuan

Ubah step opening narration supaya image thumbnail selalu diambil dari:

```text
assets/thumbnail/<videoId>.<ext>
```

Contoh:

```text
assets/thumbnail/3mLbMqNlIgM.png
assets/thumbnail/3mLbMqNlIgM.jpg
```

Tidak boleh ada lagi generate image thumbnail pada step opening narration.

## Kondisi Saat Ini

Opening narration dijalankan lewat endpoint:

```text
POST /jobs/steps/opening
```

di `api_server.py`, lalu memanggil:

```text
scripts/opening_narrator.py
```

Saat ini `scripts/opening_narrator.py` masih:

- import `generate_thumbnail` dari `scripts/auto_thumbnail.py`
- membuat thumbnail overlay dari `--image` + `--thumbnail-title`
- membuat auto thumbnail dari source video / short frame jika `--image` tidak ada
- fallback extract frame dari short menjadi `opening/short_*_thumb.jpg`

Parameter API juga masih meneruskan field yang memicu generate/overlay thumbnail:

- `opening_thumbnail_title`
- `opening_thumbnail_talents`
- `opening_thumbnail_font`
- `opening_upload_title`
- `opening_source_title`

## Perubahan Utama

1. Tambahkan resolver thumbnail statis berdasarkan `video_id`.
2. Hentikan semua auto-generate thumbnail di opening narration.
3. Jadikan missing thumbnail sebagai error jelas sebelum job opening berjalan.
4. Tetap gunakan thumbnail statis itu sebagai visual pembuka untuk `generate_opening_video`.

## Rekomendasi Implementasi

### 1. Tambah helper resolver di `api_server.py`

Tambahkan konstanta:

```python
THUMBNAIL_ASSET_DIR = APP_DIR / "assets" / "thumbnail"
THUMBNAIL_ASSET_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
```

Tambahkan helper:

```python
def find_static_opening_thumbnail(video_id: str) -> Optional[Path]:
    for ext in THUMBNAIL_ASSET_EXTENSIONS:
        path = THUMBNAIL_ASSET_DIR / f"{video_id}{ext}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None
```

Catatan:

- Nama file harus persis sama dengan `video_id`.
- Extension boleh dibatasi ke format yang aman untuk ffmpeg: `.png`, `.jpg`, `.jpeg`, `.webp`.
- Jika ingin strict hanya satu format, pilih `.png`; tapi kondisi aset saat ini sudah punya contoh `.png`.

### 2. Ubah endpoint opening di `api_server.py`

Di `create_opening_job`, setelah `video_id` didapat dan input render divalidasi:

```python
thumbnail_path = find_static_opening_thumbnail(video_id)
if not thumbnail_path:
    raise HTTPException(
        status_code=400,
        detail=(
            "Opening thumbnail asset not found. "
            f"Expected assets/thumbnail/{video_id}.png|jpg|jpeg|webp"
        ),
    )
```

Lalu selalu kirim:

```python
cmd.extend(["--image", str(thumbnail_path)])
```

Jangan lagi bergantung pada `request.opening_image` untuk opening narration.

### 3. Stop meneruskan parameter generate thumbnail dari API

Hapus atau abaikan blok ini dari command opening:

```python
if request.opening_thumbnail_title:
    cmd.extend(["--thumbnail-title", ...])
if request.opening_thumbnail_talents:
    ...
if request.opening_thumbnail_font:
    ...
if request.opening_upload_title:
    ...
if request.opening_source_title:
    ...
```

Field boleh tetap ada di `StepRequest` sementara untuk backward compatibility payload n8n, tetapi tidak digunakan lagi untuk generate image opening.

### 4. Sederhanakan `scripts/opening_narrator.py`

Hapus dependency opening terhadap `auto_thumbnail`:

```python
try:
    from auto_thumbnail import generate_thumbnail as generate_auto_thumbnail
except Exception:
    generate_auto_thumbnail = None
```

Hapus logic:

- `effective_thumbnail_title`
- `auto_thumbnail_path`
- `generate_auto_thumbnail(...)` untuk title overlay
- `generate_auto_thumbnail(...)` untuk auto thumbnail dari source video/short frame
- fallback `_extract_thumbnail(...)` untuk membuat `short_*_thumb.jpg`

Ganti dengan logic strict:

```python
thumbnail = image_path if image_path and Path(image_path).is_file() else None
if not thumbnail:
    return {
        "status": "failed",
        "message": "opening_thumbnail_asset_missing",
        "expected": image_path,
        "processed_count": len(results),
        "results": results,
    }
```

Setelah itu langsung panggil `generate_opening_video(... thumbnail_path=thumbnail ...)`.

### 5. Bersihkan argumen CLI yang tidak dipakai

Di `scripts/opening_narrator.py`, hapus atau deprecate parser args berikut:

- `--thumbnail-title`
- `--thumbnail-talent`
- `--source-video`
- `--thumbnail-font`
- `--upload-title`
- `--source-title`

Rekomendasi aman:

- Untuk tahap pertama, tetap terima argumen tersebut agar command lama tidak langsung rusak.
- Jangan pakai nilainya.
- Update help text menjadi deprecated jika masih dipertahankan.

### 6. Update cleanup artifact

Di `_cleanup_previous_opening_artifacts`, artifact auto thumbnail lama boleh tetap dibersihkan:

```python
short_*_thumb.jpg
short_*_auto_thumbnail.jpg
short_*_auto_thumbnail.json
short_*_opening_title.jpg
short_*_opening_title.json
```

Tetapi setelah perubahan ini, step opening baru tidak boleh membuat file-file tersebut lagi.

### 7. Update n8n / payload caller

Node n8n opening saat ini masih mengirim:

- `opening_thumbnail_title`
- `opening_thumbnail_font`

Karena API akan ignore field ini, flow tetap bisa berjalan. Namun payload sebaiknya dibersihkan:

- tidak perlu kirim `opening_thumbnail_title`
- tidak perlu kirim `opening_thumbnail_font`
- tidak perlu kirim `opening_image`

Syarat baru sebelum opening step:

```text
assets/thumbnail/<videoId>.png
```

atau extension lain yang disupport harus sudah ada.

## Acceptance Criteria

- Opening narration tidak lagi memanggil `scripts/auto_thumbnail.py`.
- Tidak ada file baru seperti ini saat opening berjalan:
  - `opening/short_*_auto_thumbnail.jpg`
  - `opening/short_*_opening_title.jpg`
  - `opening/short_*_thumb.jpg`
- Opening memakai image dari `assets/thumbnail/<videoId>.<ext>`.
- Jika thumbnail asset tidak ada, endpoint `/jobs/steps/opening` gagal dengan error yang jelas.
- Existing shorts tetap diproses menjadi video final dengan opening narration.
- Field thumbnail lama dari payload tidak memicu generate image apa pun.

## Validasi

1. Pastikan asset ada:

```bash
ls -l assets/thumbnail/3mLbMqNlIgM.png
```

2. Syntax check:

```bash
python3 -m py_compile api_server.py scripts/opening_narrator.py
```

3. Jalankan opening step untuk video yang punya asset thumbnail.

4. Cek log command opening harus berisi:

```text
--image /Users/agusrachman/Documents/Codex/content-short/assets/thumbnail/<videoId>.<ext>
```

5. Cek folder opening tidak membuat auto thumbnail baru:

```bash
find storage/free-viral-shorts/<videoId>/opening -maxdepth 1 -type f
```

6. Test negative case dengan videoId tanpa asset thumbnail:

Expected result:

```text
400 Opening thumbnail asset not found
```

## Risiko

- Jika ada workflow lama yang mengandalkan `opening_thumbnail_title` untuk membuat overlay teks, behavior itu akan hilang.
- Jika asset thumbnail belum disiapkan sebelum opening step, opening akan gagal lebih awal.
- Jika filename memakai suffix lama seperti `<videoId>_thumbnail.png`, file tidak akan ditemukan. Naming harus diseragamkan menjadi `<videoId>.png` atau extension lain yang disupport.

## Catatan Lanjutan

`generate_content.py` saat ini masih mencari file dari Downloads dengan nama:

```text
<videoId>_thumbnail.jpg/png
```

Jika flow ini masih dipakai, perlu plan terpisah atau perubahan tambahan supaya thumbnail dipindah/direname ke:

```text
assets/thumbnail/<videoId>.png
```
