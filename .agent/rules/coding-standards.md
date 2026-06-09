# Coding Standards

## General

- Gunakan perubahan paling minimal dan aman.
- Jangan mengubah file yang tidak relevan.
- Jangan membuat abstraction berlebihan.
- Jangan mengganti stack existing.
- Ikuti style kode yang sudah ada.
- Prioritaskan readability dan maintainability.

## Error Handling

- Error harus jelas dan actionable.
- Jangan swallow error tanpa logging.
- Untuk batch process, error per item harus dicatat.
- Jangan menghentikan seluruh proses jika hanya satu item gagal, kecuali fatal.

## API

- Response API harus konsisten.
- Jangan ubah contract existing tanpa dokumentasi.
- Jika menambah field, pastikan backward compatible.
- Validasi input harus jelas.

## UI

- State loading, success, failed, pending, dan skipped harus terlihat.
- Button harus jelas fungsinya.
- Field upload multiple file harus memberi feedback jumlah file.
- Transcript card harus punya copy transcript dan copy prompt.
