# Testing Rules

Setelah melakukan perubahan, agent wajib mencoba validasi berikut sesuai stack yang tersedia:

## Node.js / TypeScript

Cek command yang tersedia di `package.json`.

Prioritas:

```bash
npm run lint
npm run test
npm run build
```

Jika menggunakan pnpm:

```bash
pnpm lint
pnpm test
pnpm build
```

Jika menggunakan yarn:

```bash
yarn lint
yarn test
yarn build
```

## Python

Jika ada project Python:

```bash
python -m pytest
python -m compileall .
```

## Docker

Jangan menjalankan docker command berat tanpa instruksi eksplisit.

## Validation Report

Setelah validasi, agent harus melaporkan:

* Command yang dijalankan
* Result sukses/gagal
* Error jika ada
* Apakah error berasal dari perubahan agent atau sudah existing
