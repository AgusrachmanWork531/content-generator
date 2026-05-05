 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app/services/clipper_engine.py b/app/services/clipper_engine.py
index 9f4e96514a7d947cbe35e8f9a71495791c07eba3..c80672a432da21446ba73320daa14e1acc858793 100644
--- a/app/services/clipper_engine.py
+++ b/app/services/clipper_engine.py
@@ -125,73 +125,78 @@ def _decide_strategy(
         target = detections[0]["face_box"] or detections[0]["person_box"]
         return "TRACK", target
 
     # Multiple people: check if group fits within crop width
     person_boxes = [d["person_box"] for d in detections]
     group_box = _get_enclosing_box(person_boxes)
     group_width = group_box[2] - group_box[0]
     max_crop_width = frame_height * ASPECT_RATIO
     if group_width < max_crop_width:
         return "TRACK", group_box
     return "LETTERBOX", None
 
 
 def _calculate_crop_box(
     target_box: List[int], frame_width: int, frame_height: int, 
     prev_cx: float, prev_cy: float, alpha: float = 0.12
 ) -> Tuple[int, int, int, int, float, float]:
     """
     Computes (x1, y1, x2, y2) with Digital Zoom, EMA smoothing and Face Y-anchoring.
     """
     # 0. Digital Zoom Configuration (1.15x zoom to allow centering edge subjects)
     zoom_factor = 1.15
     
     # 1. Calculate Raw Target
     target_cx = (target_box[0] + target_box[2]) / 2 / frame_width
-    target_cy = target_box[1] / frame_height 
+    # Use center Y (not top edge) to prevent upward drift/out-of-frame crops
+    target_cy = ((target_box[1] + target_box[3]) / 2) / frame_height
 
     # 2. Apply EMA Smoothing
     new_cx = (alpha * target_cx) + (1 - alpha) * prev_cx
     new_cy = (alpha * target_cy) + (1 - alpha) * prev_cy
 
     # 3. Calculate Crop Window with Zoom
     # We crop a smaller area and then resize to target_height
     crop_h = int(frame_height / zoom_factor)
     crop_w = int(crop_h * ASPECT_RATIO)
+
+    # Hard guard: never allow crop box larger than source frame
+    crop_w = min(crop_w, frame_width)
+    crop_h = min(crop_h, frame_height)
     
     # X-axis clamping with margin enforcement
     # center of crop = new_cx * frame_width
     x1 = int(new_cx * frame_width - crop_w / 2)
     if x1 < 0: x1 = 0
-    if x1 + crop_w > frame_width: x1 = frame_width - crop_w
+    if x1 + crop_w > frame_width: x1 = max(0, frame_width - crop_w)
     x2 = x1 + crop_w
 
     # Y-axis Framing (Face Y-Anchor at 30%)
     face_y_in_frame = new_cy * frame_height
     y1 = int(face_y_in_frame - (crop_h * 0.30))
     if y1 < 0: y1 = 0
-    if y1 + crop_h > frame_height: y1 = frame_height - crop_h
+    if y1 + crop_h > frame_height: y1 = max(0, frame_height - crop_h)
     y2 = y1 + crop_h
 
     return x1, y1, x2, y2, new_cx, new_cy
 
 
 # ─── Audio Helpers ────────────────────────────────────────────────────────────
 
 def _has_audio(video_path: str) -> bool:
     try:
         r = subprocess.run(
             ["ffprobe", "-v", "error", "-select_streams", "a",
              "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path],
             capture_output=True, text=True,
         )
         return r.returncode == 0 and "audio" in r.stdout
     except FileNotFoundError:
         return True
 
 
 def _get_stream_start(video_path: str, stream: str = "v:0") -> float:
     try:
         r = subprocess.run(
             ["ffprobe", "-v", "error", "-select_streams", stream,
              "-show_entries", "stream=start_time", "-of", "csv=p=0", video_path],
             capture_output=True, text=True,
diff --git a/docs/split_frame_analysis_2026-05-04.md b/docs/split_frame_analysis_2026-05-04.md
new file mode 100644
index 0000000000000000000000000000000000000000..8a97a1a457651b03218dee6964cb53ec662f9133
--- /dev/null
+++ b/docs/split_frame_analysis_2026-05-04.md
@@ -0,0 +1,68 @@
+# Analisa Out-of-Frame + Rekomendasi Split-Frame (2026-05-04)
+
+## 1) Temuan akar masalah di project
+
+Berdasarkan audit `app/services/clipper_engine.py`, issue **subjek terlihat keluar frame** paling kuat berasal dari 3 titik:
+
+1. **Bias Y-anchor ke sisi atas box**: `target_cy` dihitung dari `target_box[1]` (top edge), bukan titik tengah wajah/tubuh. Ini mendorong crop naik berlebihan saat subjek bergerak.  
+2. **Guard ukuran crop belum keras**: `crop_w/crop_h` bisa menghasilkan nilai yang terlalu agresif pada kombinasi resolusi tertentu, lalu clamping menjadi borderline.  
+3. **Engine belum punya split-frame aktual**: strategy saat multi-person hanya `TRACK` atau `LETTERBOX`; belum ada mode komposisi `SPLIT` sehingga saat 2 speaker berjauhan, sistem fallback ke letterbox (terasa “jauh” / framing buruk).
+
+## 2) Patch yang diterapkan di codebase
+
+Saya menerapkan hardening pada crop box agar lebih stabil:
+
+- Ubah `target_cy` ke **center Y** dari target box (`(y1+y2)/2`) untuk menghindari drift ke atas.
+- Tambahkan **hard guard** `crop_w <= frame_width` dan `crop_h <= frame_height`.
+- Perketat clamping `x1/y1` agar tidak menghasilkan posisi negatif implisit pada edge-case.
+
+## 3) Mekanisme split-frame paling mutakhir (benchmark tool clip generator)
+
+### A. Pola yang dipakai tools modern
+
+Dari referensi dokumentasi tools:
+
+- **OpusClip Layout & Reframing**: menyediakan mode split untuk menampilkan dua speaker sekaligus, dengan catatan split efektif saat kedua speaker memang tampil bersamaan di frame asli.
+- **OpusClip Face Tracking**: auto reframe mengikuti speaker aktif/bergerak untuk menjaga engagement.
+- **Adobe Premiere Auto Reframe**: motion-aware reframing untuk adaptasi rasio platform, menjaga action tetap in-frame.
+- **FFmpeg stack/xstack**: fondasi teknis untuk komposisi multi-panel (split layar) secara deterministik.
+
+### B. Desain SOTA yang relevan untuk repo ini
+
+Rekomendasi pipeline split-frame hybrid:
+
+1. **Track-First**: multi-object tracker (ID stabil per speaker) + confidence smoothing.
+2. **Distance-Gated Layout**:
+   - `focus mode`: saat distance antar speaker kecil / overlap tinggi.
+   - `split mode`: saat distance melewati threshold dan kedua speaker visible.
+3. **Active-Speaker Aware**:
+   - gunakan VAD/audio energy per window,
+   - panel speaker aktif diberi porsi lebih besar (mis. 60/40 adaptive split).
+4. **Hysteresis + Minimum Hold**:
+   - cegah layout flip-flop (hold 2–3 detik per mode).
+5. **Safe-Zone Constraint**:
+   - wajah selalu di area aman (atas 1/3), margin teks/subtitle tidak menimpa dagu/mulut.
+6. **Fail-safe**:
+   - jika tracking drop > N frame, fallback ke letterbox sementara.
+
+### C. Implementasi cepat berbasis FFmpeg/OpenCV
+
+- `TRACK`: crop dinamis seperti engine sekarang (sudah dipatch).
+- `SPLIT`: render dua crop stream lalu gabung `vstack`/`hstack`/`xstack`.
+- **Adaptive split**: ubah scale panel berdasarkan speaker activity score.
+
+## 4) Prioritas implementasi lanjutan (urut dampak)
+
+1. Tambah mode strategi baru `SPLIT` pada `_decide_strategy` + render path khusus.
+2. Tambah per-frame/segment speaker activity scorer (VAD + mouth/pose proxy).
+3. Tambah objective metric QA:
+   - % frame wajah keluar safe-zone,
+   - layout switch per menit,
+   - subtitle-over-face collision rate.
+
+## 5) Referensi
+
+- OpusClip — Layout and Reframing: https://help.opus.pro/docs/article/layout-and-reframing
+- OpusClip — Face Tracking: https://help.opus.pro/docs/article/how-to-enable-face-tracking
+- Adobe Premiere — Auto Reframe overview: https://helpx.adobe.com/premiere/desktop/add-video-effects/commonly-used-effects/auto-reframe-overview.html
+- FFmpeg Filters (hstack/vstack/xstack): https://ffmpeg.org/ffmpeg-filters.html
 
EOF
)