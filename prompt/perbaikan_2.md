

```markdown
# 🛠️ Prompt Instruksi: Perbaikan Bug Unpacking & Implementasi Loading State

## 🎯 Tujuan Utama
1. Memperbaiki error sistem `too many values to unpack (expected 2)` yang terjadi pada *pipeline* pemrosesan video.
2. Mengimplementasikan *loading state* atau indikator progres yang proper saat proses *rendering* FFmpeg berlangsung, sehingga aplikasi/sistem tidak terlihat *hang* atau diam tanpa respon.

## 🔍 Analisa & Rencana Solusi
Berdasarkan log error dan arsitektur kode:
*   **Akar Masalah Error:** Fungsi `analyze_video` pada `clipper_engine_2.py` mengembalikan 4 nilai (metadata, fps, width, height)[cite: 3], namun `clip_processor.py` hanya menangkap 2 nilai. Selain itu, metode `split()` pada `ffmpeg-python` mengembalikan satu *node* yang jika dipecah secara paksa akan memicu *error unpack*[cite: 3].
*   **Solusi Loading State:** Karena eksekusi `ffmpeg.run()` bersifat *blocking*, kita akan mengimplementasikan skrip pemantauan (progress tracker) menggunakan library bawaan atau dengan menjalankan proses FFmpeg secara asinkron menggunakan `subprocess.Popen` untuk membaca *output* progres (waktu/frame) secara berkala, lalu mengirimkannya ke sistem *log* atau *database* status.

---

## 💻 Instruksi Implementasi Langkah-demi-Langkah

### Tahap 1: Perbaiki Penangkapan Variabel di `clip_processor.py`
Sesuaikan pemanggilan fungsi agar menangkap keempat nilai dan meneruskannya ke fungsi `render`.

1. Cari baris pemanggilan `clipper.analyze_video` dan ubah menjadi:
   ```python
   # Menangkap 4 nilai sesuai dengan return dari clipper_engine_2.py
   metadata, fps, width, height = clipper.analyze_video(final_path)
   ```
2. Pastikan pemanggilan `clipper.render` menyertakan parameter dimensi tersebut karena fungsi `render` membutuhkannya[cite: 3]:
   ```python
   clipper.render(
       input_path=final_path, 
       output_path=reframe_path, 
       metadata=smoothed,
       original_width=width,   # Parameter wajib ditambahkan
       original_height=height, # Parameter wajib ditambahkan
       title=video_title,
       ass_path=ass_path, 
       anti_bot_vfx=request.anti_bot_vfx,
       use_broll=request.satisfying
   )
   ```

### Tahap 2: Amankan Syntax FFmpeg di `clipper_engine_2.py`
Ubah cara pemecahan *stream* video agar tidak menyebabkan error *unpacking*[cite: 3].

1. Cari bagian "Recursive split to get 3 independent streams safely".
2. Ubah baris pemanggilan `split()`[cite: 3] menjadi seperti berikut:
   ```python
   # Cara yang aman untuk memecah stream ffmpeg-python
   splits1 = v_std.split()
   v_top_node = splits1[0]
   v_temp = splits1[1]
   
   splits2 = v_temp.split()
   v_bot_node = splits2[0]
   v_foc_node = splits2[1]
   ```

### Tahap 3: Implementasi Loading State yang Proper
Alih-alih menggunakan `ffmpeg.run()` yang mengunci (*block*) proses tanpa umpan balik[cite: 3], kita akan mengkompilasi *command* FFmpeg dan menjalankannya dengan asinkron/subprocess agar kita bisa menangkap log progresnya.

1. Di dalam `clipper_engine_2.py` pada fungsi `render`, ubah bagian eksekusi `ffmpeg.run(...)`[cite: 3] menjadi menggunakan sistem *progress monitoring*.
2. Implementasikan kode berikut pada bagian `try` di akhir fungsi `render`:
   ```python
   import subprocess
   import time
   
   try:
       logger.info(f"Rendering Dynamic Phase 2 Output: {output_path}")
       vcodec_args = {'vcodec': hw_encoder, 'b:v': '10M'} if hw_encoder != 'libx264' else {'vcodec': 'libx264', 'crf': '19', 'preset': 'superfast'}
       
       # 1. Compile output node menjadi argument array
       output_node = ffmpeg.output(video, audio, output_path, **vcodec_args, acodec='aac', audio_bitrate='192k', map_metadata=-1)
       cmd = ffmpeg.compile(output_node.global_args('-fps_mode', 'cfr', '-r', '30', '-threads', '0'), overwrite_output=True)
       
       # 2. Jalankan FFmpeg menggunakan subprocess untuk memantau output
       logger.info("Memulai proses render. Silakan tunggu...")
       process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
       
       # 3. Looping untuk membaca progress (LOADING STATE)
       start_time = time.time()
       for line in process.stdout:
           # Mencari kata kunci 'time=' dari output FFmpeg untuk mengetahui progress
           if "time=" in line:
               time_str = line.split("time=")[1].split(" ")[0]
               # Cetak progress setiap beberapa waktu agar tidak terlihat hang
               elapsed = int(time.time() - start_time)
               if elapsed % 5 == 0: # Update log setiap 5 detik
                   logger.info(f"[LOADING] Rendering progress: Waktu video diproses -> {time_str}")
                   
       process.wait()
       
       if process.returncode != 0:
           raise Exception(f"FFmpeg process failed with exit code {process.returncode}")
           
       logger.info(f"✅ Dynamic Render Complete: {output_path}")
       
   except Exception as e:
       logger.error(f"❌ Dynamic Render Failed: {e}")
       raise e
   ```

## ✅ Instruksi Pengujian (Testing)
1. Simpan semua perubahan pada `clip_processor.py` dan `clipper_engine_2.py`.
2. Jalankan ulang *pipeline* pemrosesan video Anda.
3. Perhatikan konsol (*terminal/logs*). Anda seharusnya tidak lagi melihat *error* "too many values to unpack", dan Anda akan melihat log bertuliskan `[LOADING] Rendering progress: ...` yang memberikan indikasi sistem sedang bekerja secara aktif.
```