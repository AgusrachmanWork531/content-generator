# Analisa Out-of-Frame + Rekomendasi Split-Frame (2026-05-04)

## 1) Temuan akar masalah di project

Berdasarkan audit `app/services/clipper_engine.py`, issue **subjek terlihat keluar frame** paling kuat berasal dari 3 titik:

1. **Bias Y-anchor ke sisi atas box**: `target_cy` dihitung dari `target_box[1]` (top edge), bukan titik tengah wajah/tubuh. Ini mendorong crop naik berlebihan saat subjek bergerak.  
2. **Guard ukuran crop belum keras**: `crop_w/crop_h` bisa menghasilkan nilai yang terlalu agresif pada kombinasi resolusi tertentu, lalu clamping menjadi borderline.  
3. **Engine belum punya split-frame aktual**: strategy saat multi-person hanya `TRACK` atau `LETTERBOX`; belum ada mode komposisi `SPLIT` sehingga saat 2 speaker berjauhan, sistem fallback ke letterbox (terasa “jauh” / framing buruk).

## 2) Patch yang diterapkan di codebase

Saya menerapkan hardening pada crop box agar lebih stabil:

- Ubah `target_cy` ke **center Y** dari target box (`(y1+y2)/2`) untuk menghindari drift ke atas.
- Tambahkan **hard guard** `crop_w <= frame_width` dan `crop_h <= frame_height`.
- Perketat clamping `x1/y1` agar tidak menghasilkan posisi negatif implisit pada edge-case.

## 3) Mekanisme split-frame paling mutakhir (benchmark tool clip generator)

### A. Pola yang dipakai tools modern

Dari referensi dokumentasi tools:

- **OpusClip Layout & Reframing**: menyediakan mode split untuk menampilkan dua speaker sekaligus, dengan catatan split efektif saat kedua speaker memang tampil bersamaan di frame asli.
- **OpusClip Face Tracking**: auto reframe mengikuti speaker aktif/bergerak untuk menjaga engagement.
- **Adobe Premiere Auto Reframe**: motion-aware reframing untuk adaptasi rasio platform, menjaga action tetap in-frame.
- **FFmpeg stack/xstack**: fondasi teknis untuk komposisi multi-panel (split layar) secara deterministik.

### B. Desain SOTA yang relevan untuk repo ini

Rekomendasi pipeline split-frame hybrid:

1. **Track-First**: multi-object tracker (ID stabil per speaker) + confidence smoothing.
2. **Distance-Gated Layout**:
   - `focus mode`: saat distance antar speaker kecil / overlap tinggi.
   - `split mode`: saat distance melewati threshold dan kedua speaker visible.
3. **Active-Speaker Aware**:
   - gunakan VAD/audio energy per window,
   - panel speaker aktif diberi porsi lebih besar (mis. 60/40 adaptive split).
4. **Hysteresis + Minimum Hold**:
   - cegah layout flip-flop (hold 2–3 detik per mode).
5. **Safe-Zone Constraint**:
   - wajah selalu di area aman (atas 1/3), margin teks/subtitle tidak menimpa dagu/mulut.
6. **Fail-safe**:
   - jika tracking drop > N frame, fallback ke letterbox sementara.

### C. Implementasi cepat berbasis FFmpeg/OpenCV

- `TRACK`: crop dinamis seperti engine sekarang (sudah dipatch).
- `SPLIT`: render dua crop stream lalu gabung `vstack`/`hstack`/`xstack`.
- **Adaptive split**: ubah scale panel berdasarkan speaker activity score.

## 4) Prioritas implementasi lanjutan (urut dampak)

1. Tambah mode strategi baru `SPLIT` pada `_decide_strategy` + render path khusus.
2. Tambah per-frame/segment speaker activity scorer (VAD + mouth/pose proxy).
3. Tambah objective metric QA:
   - % frame wajah keluar safe-zone,
   - layout switch per menit,
   - subtitle-over-face collision rate.

## 5) Referensi

- OpusClip — Layout and Reframing: https://help.opus.pro/docs/article/layout-and-reframing
- OpusClip — Face Tracking: https://help.opus.pro/docs/article/how-to-enable-face-tracking
- Adobe Premiere — Auto Reframe overview: https://helpx.adobe.com/premiere/desktop/add-video-effects/commonly-used-effects/auto-reframe-overview.html
- FFmpeg Filters (hstack/vstack/xstack): https://ffmpeg.org/ffmpeg-filters.html
