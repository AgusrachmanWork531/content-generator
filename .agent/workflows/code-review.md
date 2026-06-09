# Workflow: Code Review

Gunakan workflow ini untuk review perubahan kode.

## Steps

1. Jalankan `git status`.
2. Jalankan `git diff --stat`.
3. Review file berubah.
4. Cari bug logic.
5. Cari security issue.
6. Cari breaking change.
7. Cari missing validation.
8. Cari missing test.

## Output

```md
## Review Summary

## Critical Issues

## Medium Issues

## Minor Suggestions

## Security Notes

## Test Coverage Notes

## Merge Recommendation
```

Merge recommendation harus salah satu:

* Safe to merge
* Safe with minor fixes
* Not safe to merge
