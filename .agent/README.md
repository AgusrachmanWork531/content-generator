# Agent Configuration

Folder ini berisi konfigurasi agent untuk Google Antigravity / AI coding agent.

## Structure

```text
.agent/
├── rules/
├── workflows/
├── skills/
└── README.md
```

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
