# Workflow: Fix Issue

Gunakan workflow ini untuk memperbaiki bug.

## Steps

1. Reproduce atau pahami error.
2. Trace sumber error.
3. Identifikasi root cause.
4. Buat patch minimal.
5. Jalankan test atau validasi.
6. Laporkan hasil.

## Rules

- Jangan refactor besar.
- Jangan ubah unrelated files.
- Jangan membuat workaround kotor jika root cause jelas.
- Jika error berasal dari config/env yang tidak tersedia, jelaskan dengan jujur.

## Output

```md
## Root Cause

## Fix Applied

## Files Changed

## Validation Result

## Remaining Risk
```
