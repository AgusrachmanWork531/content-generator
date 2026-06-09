# Workflow: Git Flow

Gunakan workflow ini hanya jika user meminta git flow.

## Safe Git Flow

1. Cek status:

```bash
git status
```

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
