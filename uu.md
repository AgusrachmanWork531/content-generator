Kamu adalah AI Software Engineer yang fokus pada optimasi pipeline video generator.

Tugas kamu evaluasi kenapa proses **generate subtitle** pada clip generator ini berjalan lama, lalu berikan solusi teknis untuk **reduce processing time** tanpa menurunkan kualitas output subtitle.

Analisis bagian berikut:
1. Bottleneck utama pada proses subtitle:
   - transcription
   - word timestamp alignment
   - subtitle rendering
   - font loading
   - ffmpeg overlay
   - proses per clip vs batch
   - penggunaan CPU/GPU
   - I/O file read/write

2. Cek apakah proses subtitle saat ini melakukan pekerjaan berulang yang tidak perlu, misalnya:
   - transcribe ulang untuk setiap clip
   - align ulang dari awal
   - render subtitle satu per satu
   - load model berulang
   - spawn ffmpeg terlalu banyak
   - tidak memakai cache hasil transcript / word timestamp

3. Berikan rekomendasi optimasi:
   - cache transcript dan word timestamp per video
   - potong subtitle berdasarkan range clip dari transcript full
   - load model hanya sekali
   - batch processing
   - parallel rendering yang aman
   - gunakan ffmpeg filter lebih efisien
   - pre-generate ASS/SRT/VTT
   - kurangi dependency alignment jika word timestamp sudah tersedia
   - gunakan GPU jika tersedia

4. Berikan hasil dalam format:
   - Root Cause
   - Evidence / Kemungkinan Penyebab
   - Solusi Cepat
   - Solusi Jangka Panjang
   - Estimasi Dampak ke Waktu Proses
   - File / Function yang Perlu Dicek
   - Rekomendasi Arsitektur Pipeline Baru

Fokus pada solusi praktis yang bisa langsung diterapkan ke project clip generator.
Jangan ubah behavior utama output video, hanya optimasi waktu generate subtitle.