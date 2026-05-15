# ArmillaryLab Rename — Second Computer Steps

Run these steps on the **second computer** after the GitHub repo has been
renamed from `astroplanner` to `armillarylab` and the rename branch has
been merged to `main` and pushed from the first computer.

All commands assume PowerShell on Windows and a working directory at the
repo root.

## 1. Stop anything that has the repo open

Quit VS Code / Cursor / any running `flask` dev server in this repo so
no process is holding the database file open.

## 2. Update the git remote URL

```powershell
git remote -v                                                              # confirm current URL still points at .../astroplanner.git
git remote set-url origin https://github.com/salehram/armillarylab.git
git remote -v                                                              # confirm it now points at .../armillarylab.git
git fetch --all --prune
```

> GitHub keeps an indefinite redirect from the old URL, so even if you
> skip `set-url` for now, fetches will still work. Updating it is just
> hygiene.

## 3. Sync `main` and clean up the old branch

```powershell
git checkout main
git pull
git branch -D rename/armillarylab 2>$null                                  # only if you ever had this branch locally; harmless if not
```

If `git pull` refuses with **untracked files would be overwritten**,
move those paths aside (for example rename `uploads` or `armillarylab.db`),
then run `git pull` again. Resolve any edited tracked files (for example
`.gitignore`) with `git restore <file>` if you only want to match
`origin/main`.

Your two open feature branches (`postgresql-support`,
`feature/filter-channel-management`) do **not** need any special
handling. Next time you work on either, just rebase it on top of the new
`main` as usual:

```powershell
git checkout postgresql-support
git rebase main
# resolve any conflicts (likely just renamed strings) and continue
```

## 4. Rename the local SQLite database file

The default DB filename in code changed from `astroplanner.db` to
`armillarylab.db`. Rename it to match (data is preserved):

```powershell
if (Test-Path astroplanner.db) {
    Rename-Item astroplanner.db armillarylab.db
}
Get-ChildItem *.db                                                         # should now show armillarylab.db
```

If you don't have an `astroplanner.db` on this machine (e.g. you've been
working only on PostgreSQL or have a fresh clone), skip this step. A
fresh `armillarylab.db` will be created automatically on first run.

## 5. (If you maintain a `.env`) update DB references

If you have a local `.env` that pins the SQLite filename or PostgreSQL
DB/user name, update those values:

- `DATABASE_URL=sqlite:///armillarylab.db` (if you set it explicitly)
- `DB_NAME=armillarylab`, `DB_USER=armillarylab` (PostgreSQL only)

If you instead rely on the code defaults, skip — the defaults are
already correct in the renamed code.

## 6. (Optional, once-per-machine) refresh the dev venv

If you want to run tests or rebuild branding assets on this machine,
install the optional dev deps that were added during the rename.

Use the `Scripts` folder from **your** virtualenv at the repo root (this
machine may use `venv` rather than `dev`):

```powershell
.\venv\Scripts\pip.exe install -r requirements.txt
# or:  .\dev\Scripts\pip.exe install -r requirements.txt
```

This pulls in `pytest`, `pytest-flask`, `pytest-cov`, and `Pillow` (the
last one is only needed to re-run `branding/_make_assets.py`).

## 7. Smoke test

```powershell
$env:FLASK_APP='app.py'
.\venv\Scripts\flask.exe db info                                          # should print "ArmillaryLab Database Configuration" and the armillarylab.db path
.\venv\Scripts\flask.exe run                                              # then open http://127.0.0.1:5000/ and confirm the new logo and title
```
(Substitute `dev` for `venv` if that is what you use.)

## Rollback (if anything goes wrong)

The rename is mechanical and fully reversible:

```powershell
git remote set-url origin https://github.com/salehram/astroplanner.git    # if GitHub side has not been renamed yet
Rename-Item armillarylab.db astroplanner.db                                # if you renamed the DB file
```

The GitHub redirect means an out-of-date remote URL on this machine is
harmless, not blocking.
