# 🎬 Prompt Instruksi: Penyesuaian Pipeline Auto-Clipper (Split-Screen & Overlay)

## 🎯 Tujuan Utama
Memodifikasi *pipeline* pemrosesan video `Python` dan `FFmpeg` agar menghasilkan *output* vertikal (9:16) yang sama persis dengan referensi `final_v_clip_3ee7f11e.mp4`. 

## 🔍 Analisa & Aturan Bisnis (Business Rules)
Sistem harus mengabaikan beberapa perilaku *default* dan mengimplementasikan aturan berikut:
1. **Bypass Intro Merge:** Jangan gabungkan video intro terpisah di awal video.
2. **Split-Screen Wajah (Atas-Bawah):** Jika terdapat dua atau lebih wajah dalam satu *frame* horizontal, sistem harus membagi layar vertikal menjadi dua (atas dan bawah). Layar atas melacak wajah paling kiri, layar bawah melacak wajah paling kanan.
3. **Hardcoded Watermark & Title:** Tambahkan teks judul statis di tengah layar dan *watermark* transparan ("KILASAN VIDEO") menggunakan filter `drawtext` FFmpeg.
4. **Disable B-Roll:** Jangan gunakan layout tumpuk B-Roll dari folder eksternal. Gunakan format murni dari sumber video utama.

---

## 💻 Implementasi Kode

### File 1: `clipper_engine.py`

**1. Tambahkan fungsi pelacakan ganda (Kiri & Kanan):**
Ganti metode pelacakan tunggal dengan fungsi baru untuk mengambil koordinat `x_top` dan `x_bot`.
```python
    def get_split_centers(self, frame_bgr) -> Tuple[float, float]:
        """Mengembalikan dua titik tengah X (kiri dan kanan) untuk Split Screen Atas-Bawah"""
        height, width, _ = frame_bgr.shape
        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        
        faces_x = []

        if self.detector:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            res = self.detector.detect(mp_image)
            if res.detections:
                for detection in res.detections:
                    bbox = detection.bounding_box
                    faces_x.append(float((bbox.origin_x + bbox.width / 2) / width))

        if not faces_x and getattr(self, 'yolo_model', None):
            results = self.yolo_model.predict(frame_bgr, classes=[0], conf=0.35, verbose=False)
            if results and len(results[0].boxes) > 0:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                for box in boxes:
                    faces_x.append(float((box[0] + box[2]) / 2 / width))

        if len(faces_x) == 0:
            return (0.5, 0.5)
        elif len(faces_x) == 1:
            return (faces_x[0], faces_x[0]) 
        else:
            faces_x.sort() 
            return (faces_x[0], faces_x[-1])
```

**2. Update Perekaman Metadata (`analyze_video` & `smooth_centers`):**
Rekam kedua variabel `x_top` dan `x_bot` ke dalam _array_ metadata, bukan hanya `x`.
```python
# Di dalam loop analyze_video()
current_x_top, current_x_bot = self.get_split_centers(frame)

if abs(current_x_top - last_center_x_top) < DEAD_ZONE: current_x_top = last_center_x_top
if abs(current_x_bot - last_center_x_bot) < DEAD_ZONE: current_x_bot = last_center_x_bot

last_center_x_top = current_x_top
last_center_x_bot = current_x_bot
# ...
metadata.append({
    "time": current_time,
    "x_top": current_x_top,
    "x_bot": current_x_bot,
    # ... parameter lain tetap
})
```

**3. Rombak Fungsi Rendering (`render`):**
Terapkan logika filter FFmpeg untuk memotong dua layar terpisah, menumpuknya dengan `vstack`, dan menambahkan teks menggunakan `drawtext`.
```python
    def render(self, input_path: str, output_path: str, metadata: List[Dict], original_width: int, original_height: int, title: str = None, ass_path: str = None, anti_bot_vfx: bool = True, use_broll: bool = False):
        hw_encoder = self._detect_hw_encoder()
        stream = ffmpeg.input(input_path)
        
        v_main = stream.video.filter('fps', fps=30).filter('setpts', 'PTS-STARTPTS').filter('format', 'yuv420p')
        a_main = stream.audio.filter('asetpts', 'PTS-STARTPTS').filter('aresample', 48000).filter('loudnorm', I=-14, TP=-1, LRA=7)
        
        # Kalkulasi lebar crop untuk layar 9:8 (Setengah dari layar 9:16)
        crop_w = int(original_height * (1080 / 960))
        
        x_parts_top, x_parts_bot = [], []
        
        for i in range(len(metadata) - 1):
            t_start = metadata[i]['time']
            t_end = metadata[i+1]['time']
            
            c_top = metadata[i]['x_top']
            px_top = max(0, min(original_width - crop_w, c_top * original_width - crop_w/2))
            x_parts_top.append(f"{px_top}*between(t,{t_start:.3f},{t_end:.3f})")
            
            c_bot = metadata[i]['x_bot']
            px_bot = max(0, min(original_width - crop_w, c_bot * original_width - crop_w/2))
            x_parts_bot.append(f"{px_bot}*between(t,{t_start:.3f},{t_end:.3f})")
        
        # Eksekusi Filter Crop dan Scale
        v_top = v_main.filter('crop', crop_w, 'ih', x=" + ".join(x_parts_top), y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
        v_bot = v_main.filter('crop', crop_w, 'ih', x=" + ".join(x_parts_bot), y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)

        # Tumpuk Layar Atas & Bawah
        video = ffmpeg.filter([v_top, v_bot], 'vstack')

        if ass_path and os.path.exists(ass_path):
            video = video.filter('ass', os.path.abspath(ass_path))
            
        # Hardcoded Overlay & Watermark (Sesuai Referensi)
        video = video.filter('drawtext', text='KILASAN VIDEO', fontcolor='white', alpha=0.5, fontsize=40, x='(w-text_w)/2', y='(h-text_h)/2 + 200')
        if title:
            video = video.filter('drawtext', text=title.upper(), fontcolor='white', borderw=4, bordercolor='black', fontsize=75, x='(w-text_w)/2', y='(h-text_h)/2')
            
        video, audio = audio_engine.apply_bgm_with_ducking(video, a_main)
        # Lanjutkan ke eksekusi ffmpeg.output...
```

---

### File 2: `clip_processor.py`

**1. Penyesuaian Pemanggilan Render (Step 4):**
Pastikan variabel `height` diteruskan ke dalam fungsi render.
```python
            # Di dalam bagian "Step 4: Auto-Reframe"
            clipper.render(
                final_path, reframe_path, 
                smoothed, width, height, # <-- WAJIB TAMBAH PARAMETER HEIGHT
                title=video_title,
                ass_path=ass_path, 
                anti_bot_vfx=request.anti_bot_vfx,
                use_broll=False # <-- Set False secara paksa agar B-Roll non-aktif
            )
```

**2. Bypass Video Pembuka (Step 5):**
Nonaktifkan sementara (atau bypass sepenuhnya) pemrosesan Intro Narration, karena judul sudah langsung dirender di dalam *stream* utama.
```python
        # Di dalam bagian "Step 5: Opening Narration"
        bypass_intro_merge = True # Flag untuk mematikan intro
        
        if not bypass_intro_merge and request.narration_text and request.narration_text.strip():
            # ... biarkan logika intro di sini, tapi tidak akan tereksekusi
```

## ✅ Instruksi Deployment / Testing
1. Salin dan ganti fungsi yang ada di dalam `clipper_engine.py` dan `clip_processor.py` menggunakan kode di atas.
2. Pastikan pustaka bawaan python seperti `numpy`, `cv2` (OpenCV), dan `ffmpeg-python` (`import ffmpeg`) tidak ada yang *error* atau hilang.
3. Jalankan satu uji coba proses kliping video menggunakan URL dari YouTube *podcast* yang memiliki banyak orang (lebih dari satu wajah).
4. Periksa hasil *output* (file `final_v_clip_xxx.mp4`) untuk memastikan layar sudah terbagi dua (atas-bawah) dan *watermark* terpasang dengan benar di tengah layar.