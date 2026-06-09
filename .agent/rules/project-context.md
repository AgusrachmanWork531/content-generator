# Project Context

Repository ini adalah project automation untuk membuat video short dari long video.

## Core Flow

1. Download video dari YouTube/source lain
2. Extract transcript
3. Hold sebelum render
4. Tampilkan transcript card yang bisa di-copy
5. Upload metadata clip
6. Render video short berdasarkan metadata
7. Generate subtitle
8. Generate watermark
9. Generate opening narration
10. Upload atau export hasil akhir

## Important Domain Rules

- Output JSON harus machine-readable.
- Jangan ubah format payload n8n tanpa alasan jelas.
- Jangan ubah validasi `video_id` tanpa mengecek downstream flow.
- Metadata clip bisa lebih dari satu.
- Jika multiple metadata clip diproses, render harus synchronous satu per satu.
- Jika satu metadata gagal, item berikutnya tetap diproses dan status item gagal dicatat.
- Subtitle harus support pilihan font.
- Watermark harus support pilihan font.
- UI harus user friendly dan jelas status step-nya.
- Jangan membuat breaking change pada API existing.
- Jangan menghapus compatibility dengan single metadata clip.
