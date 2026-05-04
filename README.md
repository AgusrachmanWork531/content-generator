# 🎬 YouTube AI Clipper — Phase 2 (Dynamic Intelligence)

**YouTube AI Clipper** adalah layanan otomatisasi video berbasis AI yang dirancang untuk mengubah video landscape menjadi Shorts/Reels vertikal berkualitas tinggi secara cerdas. Dilengkapi dengan **Intelligence Decision Engine**, sistem ini mampu menentukan tata letak terbaik (Split-Screen vs Single-Focus) secara otomatis berdasarkan analisis forensik subjek.

## 🚀 Fitur Utama (Phase 2)

| Fitur | Deskripsi |
| :--- | :--- |
| **Intelligence Decision Engine** | Menentukan layout secara dinamis. Beralih ke *Split-Screen* jika subjek berjauhan (>50% frame) dan *Focus* jika subjek berdekatan. |
| **AI Forensic Tracking** | Menggunakan YOLOv11 dan MediaPipe untuk melacak wajah dan tubuh secara real-time dengan akurasi tinggi. |
| **Dynamic Render Engine** | Rendering FFmpeg satu jalur yang mampu berganti layout di tengah video tanpa jeda (*seamless switching*). |
| **Progress Monitoring** | Log status `[LOADING]` secara real-time yang memantau waktu proses rendering video. |
| **Karaoke Subtitles** | Subtitle gaya viral dengan efek highlight per kata menggunakan format ASS. |
| **Automated BGM & Ducking** | Penambahan musik latar otomatis dengan efek *audio ducking* saat subjek berbicara. |

## 🛠️ Arsitektur Teknologi

- **Framework**: FastAPI (Asynchronous Python)
- **Computer Vision**: OpenCV, MediaPipe, Ultralytics YOLOv11
- **Video Processing**: FFmpeg (dengan akselerasi hardware `h264_videotoolbox` untuk Mac M1/M2)
- **Speech-to-Text**: OpenAI Whisper / YouTube Transcript API
- **Automation**: Terintegrasi penuh dengan Google Sheets dan n8n

## 📦 Instalasi

1. **Clone Repositori**:
   ```bash
   git clone https://github.com/AgusrachmanWork531/content-generator.git
   cd content-generator
   ```

2. **Setup Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Jalankan Layanan**:
   ```bash
   ./run_clipper.sh
   ```

## 📡 API Endpoints

### `POST /download-clip`
Endpoint utama untuk memproses video.

**Payload Example:**
```json
{
  "url": "https://youtube.com/watch?v=xxx",
  "start_time": "00:05:00",
  "end_time": "00:05:50",
  "auto_reframe": true,
  "add_subtitles": true,
  "anti_bot_vfx": true,
  "metaData": {
    "title": "Judul Video Viral"
  }
}
```

## 🧠 Logika Decision Engine (Phase 2)
Sistem menghitung jarak (`dist`) antara dua subjek utama (kiri dan kanan):
- **Jarak > 0.5**: Aktifkan **Split-Screen** (Atas-Bawah).
- **Jarak <= 0.5**: Aktifkan **Single Focus** (Kamera melacak titik tengah antar subjek).
- **Hysteresis**: Perpindahan mode dikunci minimal selama 3 detik untuk menjaga stabilitas visual.

---
**Author**: Antigravity AI Assistant
**Status**: Production Ready (Phase 2)
