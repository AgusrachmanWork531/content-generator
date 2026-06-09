# Workflow: Safe Refactor

Gunakan workflow ini untuk refactor aman.

## Steps

1. Identifikasi behaviour existing.
2. Jangan ubah output.
3. Jangan ubah API contract.
4. Refactor kecil dan bertahap.
5. Jalankan test.
6. Bandingkan behaviour sebelum dan sesudah.

## Rules

- Refactor harus punya alasan jelas.
- Jangan gabungkan refactor dengan fitur besar.
- Jangan hapus test.
- Jangan ubah naming public API tanpa alasan.

## Output

```md
## Refactor Goal

## Behaviour Preserved

## Files Changed

## Validation

## Risk
```
