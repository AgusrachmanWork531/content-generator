# Git Rules

Sebelum mengubah file:

```bash
git status
```

Agent harus memahami working tree saat ini.

## Rules

* Jangan overwrite perubahan user.
* Jangan commit otomatis kecuali diminta.
* Jangan push otomatis.
* Jangan force push.
* Jangan reset hard.
* Jangan clean file tanpa izin.

## Setelah perubahan

Agent harus menampilkan:

```bash
git status
git diff --stat
```

Agent juga harus memberi summary:

* File changed
* Purpose
* Risk
* How to test
