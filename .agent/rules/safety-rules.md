# Safety Rules

AI Agent tidak boleh:

1. Menghapus file secara massal.
2. Mengubah file secret.
3. Mengubah credential.
4. Melakukan force push.
5. Menjalankan command destruktif.
6. Mengubah dependency besar tanpa alasan.
7. Mengubah struktur project besar tanpa approval.
8. Menghapus test existing.
9. Menghapus logging penting.
10. Mengubah behaviour production tanpa validasi.

Jika ada kebutuhan command berisiko, agent harus berhenti dan meminta konfirmasi.
