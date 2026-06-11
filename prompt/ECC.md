# AGENT INSTRUCTION — Setup ECC / Everything Claude Code untuk Google Antigravity

## Role

Kamu adalah AI Agent Engineer yang bekerja di dalam repository ini.

Tugas kamu adalah melakukan setup **Everything Claude Code / ECC by Affaan Mustafa** agar dapat digunakan di **Google Antigravity** melalui struktur `.agent/`.

Kamu harus bekerja secara aman, terstruktur, dan tidak mengubah kode aplikasi utama kecuali memang diperlukan untuk setup agent.

---

## Main Objective

Setup repository ini agar kompatibel dengan Google Antigravity menggunakan konfigurasi ECC, meliputi:

1. Membuat struktur `.agent/`
2. Menambahkan rules project
3. Menambahkan workflows untuk AI agent
4. Menambahkan skills yang relevan
5. Membuat instruksi kerja agent agar future task lebih konsisten
6. Memastikan setup tidak merusak kode existing
7. Membuat dokumentasi cara menggunakan setup ini

---

## Important Safety Rules

Wajib ikuti semua aturan berikut:

1. Jangan menghapus file existing tanpa alasan kuat.
2. Jangan mengubah business logic aplikasi.
3. Jangan melakukan refactor kode aplikasi.
4. Jangan menjalankan command destruktif seperti:

   * `rm -rf`
   * `git reset --hard`
   * `git clean -fd`
   * `docker system prune`
   * `git push --force`
5. Jangan mengubah `.env`, secret, token, credential, atau file konfigurasi sensitif.
6. Jangan melakukan commit otomatis kecuali diminta.
7. Jangan install package baru kecuali benar-benar diperlukan.
8. Semua perubahan harus terbatas pada file setup agent seperti:

   * `.agent/`
   * dokumentasi `.md`
   * optional script helper non-destruktif
9. Jika menemukan konflik antara instruksi ECC dan struktur repo saat ini, pilih pendekatan paling aman.
10. Sebelum melakukan perubahan, tampilkan plan singkat.

---

## Expected Folder Structure

Buat atau lengkapi struktur berikut di root repository:

```text
.agent/
├── rules/
│   ├── project-context.md
│   ├── coding-standards.md
│   ├── safety-rules.md
│   ├── testing-rules.md
│   ├── git-rules.md
│   └── output-format-rules.md
├── workflows/
│   ├── plan-first.md
│   ├── fix-issue.md
│   ├── code-review.md
│   ├── implement-feature.md
│   ├── refactor-safe.md
│   ├── test-and-validate.md
│   └── git-flow.md
├── skills/
│   ├── planner.md
│   ├── codebase-analyzer.md
│   ├── bug-fixer.md
│   ├── code-reviewer.md
│   ├── test-writer.md
│   ├── security-checker.md
│   └── documentation-writer.md
└── README.md
```

Jika folder `.agent/` sudah ada, jangan overwrite membabi-buta. Merge dengan aman.

---

## Project Context Rule

Buat file:

```text
.agent/rules/project-context.md
```

Isi file dengan konteks berikut:

```md
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
```

---

## Coding Standards Rule

Buat file:

```text
.agent/rules/coding-standards.md
```

Isi:

```md
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
```

---

## Safety Rules

Buat file:

```text
.agent/rules/safety-rules.md
```

Isi:

```md
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
```

---

## Testing Rules

Buat file:

```text
.agent/rules/testing-rules.md
```

Isi:

````md
# Testing Rules

Setelah melakukan perubahan, agent wajib mencoba validasi berikut sesuai stack yang tersedia:

## Node.js / TypeScript

Cek command yang tersedia di `package.json`.

Prioritas:

```bash
npm run lint
npm run test
npm run build
````

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

````

---

## Git Rules

Buat file:

```text
.agent/rules/git-rules.md
````

Isi:

````md
# Git Rules

Sebelum mengubah file:

```bash
git status
````

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

````

---

## Output Format Rules

Buat file:

```text
.agent/rules/output-format-rules.md
````

Isi:

````md
# Output Format Rules

Setiap selesai mengerjakan task, response agent harus menggunakan format berikut:

## Summary

Jelaskan secara singkat apa yang dikerjakan.

## Files Changed

List file yang berubah:

```text
path/to/file.ext
- perubahan utama
- alasan perubahan
````

## Validation

Tampilkan command validasi yang dijalankan.

```text
Command:
Result:
Notes:
```

## Risk Notes

Tampilkan potensi risiko jika ada.

## Next Step

Berikan rekomendasi langkah berikutnya.

````

---

## Workflow: Plan First

Buat file:

```text
.agent/workflows/plan-first.md
````

Isi:

````md
# Workflow: Plan First

Gunakan workflow ini sebelum melakukan task besar.

## Steps

1. Baca struktur repository.
2. Identifikasi file yang relevan.
3. Jangan edit file dulu.
4. Buat implementation plan.
5. Jelaskan risiko.
6. Tunggu instruksi lanjut jika task berisiko tinggi.

## Output

```md
## Repository Understanding

## Relevant Files

## Proposed Plan

## Risks

## Questions / Assumptions
````

````

---

## Workflow: Fix Issue

Buat file:

```text
.agent/workflows/fix-issue.md
````

Isi:

````md
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
````

````

---

## Workflow: Implement Feature

Buat file:

```text
.agent/workflows/implement-feature.md
````

Isi:

````md
# Workflow: Implement Feature

Gunakan workflow ini untuk implementasi fitur baru.

## Steps

1. Pahami requirement.
2. Cari current implementation.
3. Tentukan file yang perlu diubah.
4. Buat plan singkat.
5. Implementasi bertahap.
6. Pastikan backward compatible.
7. Jalankan validasi.
8. Berikan summary.

## Rules

- Jangan menghapus fitur existing.
- Jangan ubah API contract tanpa alasan kuat.
- Jangan over-engineering.
- Jika ada pilihan desain, pilih yang paling sederhana dan aman.

## Output

```md
## Feature Implemented

## Files Changed

## How It Works

## Validation

## How To Test Manually

## Risks
````

````

---

## Workflow: Code Review

Buat file:

```text
.agent/workflows/code-review.md
````

Isi:

````md
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
````

Merge recommendation harus salah satu:

* Safe to merge
* Safe with minor fixes
* Not safe to merge

````

---

## Workflow: Refactor Safe

Buat file:

```text
.agent/workflows/refactor-safe.md
````

Isi:

````md
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
````

````

---

## Workflow: Test And Validate

Buat file:

```text
.agent/workflows/test-and-validate.md
````

Isi:

````md
# Workflow: Test And Validate

Gunakan workflow ini setelah perubahan kode.

## Steps

1. Cek package manager.
2. Cek command test/lint/build.
3. Jalankan validasi yang aman.
4. Catat hasil.
5. Jika gagal, analisis penyebab.

## Output

```md
## Commands Run

## Results

## Failures

## Likely Cause

## Suggested Fix
````

````

---

## Workflow: Git Flow

Buat file:

```text
.agent/workflows/git-flow.md
````

Isi:

````md
# Workflow: Git Flow

Gunakan workflow ini hanya jika user meminta git flow.

## Safe Git Flow

1. Cek status:

```bash
git status
````

2. Review perubahan:

```bash
git diff --stat
```

3. Jika diminta commit:

```bash
git add .
git commit -m "<message>"
```

4. Pull branch target:

```bash
git pull upstream master
```

5. Push branch:

```bash
git push origin master
```

## Cherry-pick Flow

Jika diminta cherry-pick ke release:

```bash
git checkout release
git pull upstream release
git cherry-pick <commit_hash>
git push origin release
```

## Forbidden

* Jangan `git push --force`
* Jangan `git reset --hard`
* Jangan `git clean -fd`
* Jangan commit tanpa instruksi user

````

---

## Skills

Buat file berikut di `.agent/skills/`.

---

### planner.md

```md
# Skill: Planner

Gunakan skill ini untuk memecah task kompleks menjadi langkah kecil.

## Responsibilities

- Memahami goal.
- Mengidentifikasi file relevan.
- Membuat plan aman.
- Menentukan risiko.
- Menentukan validasi.

## Output

```md
## Plan

1.
2.
3.

## Files To Inspect

## Risks

## Validation Plan
````

````

---

### codebase-analyzer.md

```md
# Skill: Codebase Analyzer

Gunakan skill ini untuk memahami repository.

## Responsibilities

- Membaca struktur folder.
- Mencari entry point.
- Mencari flow API/UI/worker.
- Menjelaskan dependensi antar file.
- Tidak melakukan edit.

## Output

```md
## Architecture Summary

## Main Entry Points

## Important Files

## Data Flow

## Risk Areas
````

````

---

### bug-fixer.md

```md
# Skill: Bug Fixer

Gunakan skill ini untuk memperbaiki issue.

## Responsibilities

- Cari root cause.
- Patch minimal.
- Jangan refactor besar.
- Tambahkan validasi jika perlu.
- Jalankan test.

## Output

```md
## Root Cause

## Patch

## Validation

## Remaining Risk
````

````

---

### code-reviewer.md

```md
# Skill: Code Reviewer

Gunakan skill ini untuk review kode.

## Focus

- Bug
- Security
- Breaking change
- Error handling
- Performance
- Test coverage
- Maintainability

## Output

```md
## Critical

## Medium

## Minor

## Recommendation
````

````

---

### test-writer.md

```md
# Skill: Test Writer

Gunakan skill ini untuk menulis atau memperbaiki test.

## Responsibilities

- Cari test framework existing.
- Ikuti style test existing.
- Cover happy path.
- Cover error path.
- Jangan membuat test palsu yang tidak memvalidasi behaviour.

## Output

```md
## Tests Added

## Coverage

## How To Run
````

````

---

### security-checker.md

```md
# Skill: Security Checker

Gunakan skill ini untuk review keamanan.

## Focus

- Secret leakage
- Unsafe shell command
- Path traversal
- File upload validation
- Authentication
- Authorization
- Input validation
- Dependency risk

## Output

```md
## Security Findings

## Severity

## Recommended Fix
````

````

---

### documentation-writer.md

```md
# Skill: Documentation Writer

Gunakan skill ini untuk membuat dokumentasi.

## Responsibilities

- Menjelaskan setup.
- Menjelaskan command.
- Menjelaskan flow.
- Menjelaskan troubleshooting.
- Menulis jelas dan praktis.

## Output

```md
## Documentation Added

## Usage

## Notes
````

````

---

## README untuk `.agent/`

Buat file:

```text
.agent/README.md
````

Isi:

````md
# Agent Configuration

Folder ini berisi konfigurasi agent untuk Google Antigravity / AI coding agent.

## Structure

```text
.agent/
├── rules/
├── workflows/
├── skills/
└── README.md
````

## Rules

Rules adalah instruksi global yang harus selalu diikuti agent.

## Workflows

Workflows adalah pola kerja untuk task tertentu seperti:

* planning
* fix issue
* implement feature
* code review
* testing
* git flow

## Skills

Skills adalah kemampuan khusus agent seperti:

* planner
* codebase analyzer
* bug fixer
* code reviewer
* test writer
* security checker
* documentation writer

## Recommended Usage

Untuk task besar, selalu mulai dengan:

```text
Use plan-first workflow. Analyze this repository first. Do not edit files yet.
```

Untuk bug:

```text
Use fix-issue workflow to identify root cause and patch with minimal changes.
```

Untuk review:

```text
Use code-review workflow to review current git diff.
```

## Safety

Agent tidak boleh menjalankan command destruktif, menghapus file penting, mengubah secret, atau melakukan push tanpa instruksi eksplisit.

````

---

## Final Validation

Setelah semua file dibuat, jalankan command aman berikut:

```bash
git status
find .agent -maxdepth 3 -type f | sort
````

Jika project memiliki markdown lint, jalankan jika tersedia.

Jangan menjalankan test aplikasi karena setup ini hanya menambahkan konfigurasi agent, kecuali user meminta.

---

## Final Response Format

Setelah selesai, jawab dengan format berikut:

````md
## Setup Completed

ECC-style Antigravity agent configuration has been added.

## Files Created

- `.agent/rules/project-context.md`
- `.agent/rules/coding-standards.md`
- `.agent/rules/safety-rules.md`
- `.agent/rules/testing-rules.md`
- `.agent/rules/git-rules.md`
- `.agent/rules/output-format-rules.md`
- `.agent/workflows/plan-first.md`
- `.agent/workflows/fix-issue.md`
- `.agent/workflows/code-review.md`
- `.agent/workflows/implement-feature.md`
- `.agent/workflows/refactor-safe.md`
- `.agent/workflows/test-and-validate.md`
- `.agent/workflows/git-flow.md`
- `.agent/skills/planner.md`
- `.agent/skills/codebase-analyzer.md`
- `.agent/skills/bug-fixer.md`
- `.agent/skills/code-reviewer.md`
- `.agent/skills/test-writer.md`
- `.agent/skills/security-checker.md`
- `.agent/skills/documentation-writer.md`
- `.agent/README.md`

## Validation

Command run:

```bash
git status
find .agent -maxdepth 3 -type f | sort
````

## How To Use

Open this repository in Google Antigravity, then ask:

```text
Use plan-first workflow. Analyze this repository first. Do not edit files yet.
```

## Notes

No application source code was changed.

```
```
