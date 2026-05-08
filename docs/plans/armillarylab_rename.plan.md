---
name: Rename to ArmillaryLab
overview: Coordinated rename of the project from AstroPlanner to ArmillaryLab across code, config, docs, Docker, and the SQLite database file, followed by a GitHub repo rename and remote-URL update on both machines, plus generation of three logo concepts.
todos:
  - id: phase0_branch
    content: Create docs/plans/ folder, copy this plan into docs/plans/armillarylab_rename.plan.md, create branch rename/armillarylab off main, and run a baseline flask run smoke test
    status: in_progress
  - id: phase1_code
    content: Rename APP_NAME, NINA filename, preset filename, and other in-code AstroPlanner strings in app.py, nina_integration.py, cli.py, time_utils.py
    status: pending
  - id: phase2_db
    content: Update default SQLite path and DB defaults in config/database.py, update .gitignore, and rename astroplanner.db to armillarylab.db on disk
    status: pending
  - id: phase3_templates
    content: Update <title> in templates/base.html and the <h1> in templates/index.html
    status: pending
  - id: phase4_tests
    content: Update tests/conftest.py and run_tests.py, then run pytest
    status: pending
  - id: phase5_docker
    content: Update docker-compose.yml, docker-compose.postgres.yml, .env.example, .env.production for the new name and DB defaults
    status: pending
  - id: phase6_docs
    content: Bulk-rename AstroPlanner/astroplanner across README.md, CHANGELOG.md, LICENSE, and all docs/*.md, including the README clone URL placeholder
    status: pending
  - id: phase7_verify
    content: Run flask run end-to-end, verify NINA/AstroBin downloads, run pytest, commit
    status: pending
  - id: phase8_github
    content: "Manual: rename GitHub repo, run git remote set-url on both computers, rename astroplanner.db on other computer"
    status: pending
  - id: phase9_logos
    content: Generate three logo concepts (Classical, Minimalist, App Icon) into branding/ via GenerateImage
    status: pending
isProject: false
---

# Rename AstroPlanner to ArmillaryLab

A staged plan that touches every place the old name lives, in an order that keeps the app runnable at each step. Out-of-process actions (GitHub Settings, your other computer) are called out separately so you can decide when to do them.

## Phase 0 - Branch, archive plan, and sanity

- Create a new folder `docs/plans/` in the workspace (it does not exist today).
- Copy this plan file from `c:\Users\SalehRam\.cursor\plans\rename_to_armillarylab_43bec920.plan.md` to `docs/plans/armillarylab_rename.plan.md` so a permanent, version-controlled copy lives with the repo for future reference. The cursor-local copy and the workspace copy will diverge after this point - the workspace copy is the canonical reference snapshot.
- Create a working branch off `main`, e.g. `rename/armillarylab`.
- Quick `flask run` smoke check to confirm the current state works before any edits.

## Phase 1 - Core code rename

Files that hold the brand string at runtime:

- [app.py](app.py)
  - Line 35: `APP_NAME = "AstroPlanner"` to `APP_NAME = "ArmillaryLab"`.
  - Line 934 (`export_nina_sequence`): NINA download filename `f"AstroPlanner_{target.name.replace(' ', '_')}.json"` to `f"ArmillaryLab_{target.name.replace(' ', '_')}.json"`.
  - Line 1675-1676 (`export_preset_web`): `"preset_name": "Custom Export"` description string `"Exported from AstroPlanner"` to `"Exported from ArmillaryLab"`.
  - Line 1715 (`export_preset_web`): preset download filename prefix `astroplanner_preset_` to `armillarylab_preset_`.
- [nina_integration.py](nina_integration.py)
  - Line 219: `template["Name"] = f"AstroPlanner - {target_name}"` to `f"ArmillaryLab - {target_name}"`.
- [cli.py](cli.py)
  - Line 31: header text `AstroPlanner Database Configuration` to `ArmillaryLab Database Configuration`.
  - Line 162: comment `# AstroPlanner Environment Configuration` to `# ArmillaryLab Environment Configuration`.
- [time_utils.py](time_utils.py)
  - Line 2 docstring: `for the AstroPlanner application` to `for the ArmillaryLab application`.

## Phase 2 - Database defaults and SQLite file rename

Per your decision: rename the default SQLite filename in code AND rename the file on disk.

- [config/database.py](config/database.py)
  - Line 110: default DB path `'astroplanner.db'` to `'armillarylab.db'` (in `_build_sqlite_url`).
  - Line 75: `DB_NAME` default `'astroplanner'` to `'armillarylab'`.
  - Line 76: `DB_USER` default `'astroplanner'` to `'armillarylab'`.
- [.gitignore](.gitignore)
  - Line 7: `astroplanner.db` to `armillarylab.db` (keep the broader `*.db` rule below it).
- File system: rename `astroplanner.db` to `armillarylab.db` in the working tree. (Stop the dev server first; the rename is just a file move - data is preserved unchanged.)
- The currently tracked `astroplanner.db` shows as modified in git; the rename will appear as a delete + add. We will commit the rename so the working tree matches the new defaults.

Note for your other computer (Phase 8): you will simply rename the file the same way locally; no data migration is needed.

### PostgreSQL handling

PostgreSQL support is fully kept; only naming is updated. There is no live PG database on this machine (you are on SQLite), so there is nothing to physically rename in a running database server. What this plan changes for the PG path:

- Code defaults in [config/database.py](config/database.py) lines 75-76 (`DB_NAME`, `DB_USER`) - covered above.
- Test PG URL in [tests/conftest.py](tests/conftest.py) line 41 - covered in Phase 4.
- Compose Postgres service/user/db names in [docker-compose.yml](docker-compose.yml) (commented block) and [docker-compose.postgres.yml](docker-compose.postgres.yml) - covered in Phase 5.
- Env templates in [.env.example](.env.example) and [.env.production](.env.production) - covered in Phase 5.
- PG docs ([docs/POSTGRESQL_DEPLOYMENT.md](docs/POSTGRESQL_DEPLOYMENT.md), [docs/POSTGRESQL_SUMMARY.md](docs/POSTGRESQL_SUMMARY.md), [docs/DATABASE_GUIDE.md](docs/DATABASE_GUIDE.md)) - covered in Phase 6.
- Migration engine [config/migration.py](config/migration.py) needs no functional change; it operates on whatever connection strings the configs hand it.

When you eventually deploy under the new name to PG, two clean paths are supported by the code without further edits:

1. **Fresh PG with new defaults** - create database `armillarylab` and role `armillarylab`, then `flask init-db` on the PG target (or `flask db migrate --to postgresql --target-url ...` to import from your SQLite file).
2. **Reuse existing PG infrastructure** - keep an existing `astroplanner` PG database and just set `DATABASE_URL=postgresql://...astroplanner` in `.env`. When `DATABASE_URL` is provided, the renamed code defaults are not consulted ([config/database.py](config/database.py) `_build_postgresql_url` lines 65-86).

## Phase 3 - Templates

- [templates/base.html](templates/base.html)
  - Line 5: `<title>Astrophotography Planner</title>` to `<title>ArmillaryLab - Astrophotography Planner</title>`.
  - Navbar brand and footer already use `{{ app_name }}` from the context processor in [app.py](app.py) lines 43-49, so they auto-update.
- [templates/index.html](templates/index.html)
  - Line 5: `<h1 class="h3 mb-0">Astro Planner</h1>` to `<h1 class="h3 mb-0">ArmillaryLab</h1>`.

## Phase 4 - Tests

- [tests/conftest.py](tests/conftest.py)
  - Line 41: `'postgresql://test:test@localhost:5432/test_astroplanner'` to `test_armillarylab`.
- [run_tests.py](run_tests.py): swap any `AstroPlanner` mentions in comments/banners.

Run the test suite to confirm nothing regressed.

## Phase 5 - Docker and deployment

- [Dockerfile](Dockerfile): no functional name references; verify nothing slipped in (HEALTHCHECK URL is generic).
- [docker-compose.yml](docker-compose.yml)
  - Service key `astroplanner:` to `armillarylab:`.
  - `container_name: astroplanner` to `armillarylab`.
  - In commented PostgreSQL block, default DB name/user `astroplanner` to `armillarylab`.
  - In commented `depends_on` and Postgres service, container/db names.
- [docker-compose.postgres.yml](docker-compose.postgres.yml): same service/container/db name swaps.
- [.env.example](.env.example) and [.env.production](.env.production): swap `astroplanner` mentions in comments and any default DB names/URLs to `armillarylab`. Leave actual user secrets alone.

## Phase 6 - Documentation

Bulk find-and-replace `AstroPlanner` to `ArmillaryLab` and `astroplanner` to `armillarylab` across:

- [README.md](README.md)
- [CHANGELOG.md](CHANGELOG.md) - keep historical 1.0.0/2.0.0 entries factually accurate (they shipped under the old name); add a new entry at the top noting the rename.
- [LICENSE](LICENSE) - update the copyright line if it names the project.
- All files under [docs/](docs/): `DATABASE_GUIDE.md`, `DOCKER_GUIDE.md`, `NINA_INTEGRATION.md`, `ASTROBIN_EXPORT.md`, `PALETTE_FILTER_GUIDE.md`, `PRESETS_GUIDE.md`, `POSTGRESQL_DEPLOYMENT.md`, `POSTGRESQL_SUMMARY.md`, `DEPLOYMENT_SECURITY_PLAN.md`, `FEATURES_ROADMAP.md`, `THIRD_PARTY_LICENSES.md`, `README.md`.
- Replace `https://github.com/yourusername/astroplanner.git` placeholders in `README.md` line 106 with `https://github.com/salehram/armillarylab.git` (the future URL).

## Phase 7 - Verify locally

- `flask run` and click through: home, target detail, settings, filters, palettes, NINA export (verify the downloaded filename starts with `ArmillaryLab_`), AstroBin export (still uses `AstroBin_` prefix - that's a third-party service name).
- `flask db info` should still show the new SQLite path resolving correctly.
- `pytest` to confirm tests pass.
- Commit on the `rename/armillarylab` branch.

## Phase 8 - GitHub repo rename and remote-URL update (manual)

These are user actions:

1. On GitHub: Settings to General to Rename repository - `astroplanner` to `armillarylab`. GitHub keeps an indefinite redirect from the old URL.
2. On THIS computer:
   ```
   git remote set-url origin https://github.com/salehram/armillarylab.git
   git fetch
   ```
3. On the OTHER computer: same `git remote set-url` command, plus rename the local SQLite file:
   ```
   # Windows
   ren astroplanner.db armillarylab.db
   ```
4. Merge `rename/armillarylab` to `main` and push. The two open feature branches (`postgresql-support`, `feature/filter-channel-management`) just need a rebase on top of the new `main` when next worked on; no special handling.

```mermaid
flowchart LR
    A[GitHub repo rename] --> B[git remote set-url on this computer]
    A --> C[git remote set-url on other computer]
    C --> D[Rename astroplanner.db to armillarylab.db on other computer]
    B --> E[git fetch and merge]
    D --> E
```

## Phase 9 - Logo generation (three concepts)

Once Phase 1-7 is committed, generate three logos using the GenerateImage tool, saved into a new `branding/` folder.

- Concept 1 - Classical Instrument: precise line-drawn armillary sphere (meridian, equator, ecliptic rings, central amber bead), warm gold on deep navy, scholarly serif wordmark `ArmillaryLab`. 1024x1024, transparent background. Filename `branding/armillarylab_classical.png`.
- Concept 2 - Minimalist Geometric: three thin intersecting circles forming an armillary glyph, single central dot, modern lowercase geometric sans wordmark `armillarylab`, monochrome with one accent color. 1024x1024, transparent background. Filename `branding/armillarylab_minimal.png`.
- Concept 3 (was Concept 4) - Modern App Icon: rounded-square dark navy tile, single tilted armillary ring in gold, bright central dot, no wordmark. Designed for favicons and Docker tile use. 1024x1024 square. Filename `branding/armillarylab_appicon.png`.

After generation: pick a winner, then I would propose follow-on edits to wire the logo into [templates/base.html](templates/base.html) navbar and a `static/favicon.ico` derived from the app-icon concept. That is a separate, optional step we can plan after you choose.

## Risks and rollback

- The rename is mechanical; the only data-bearing change is the `astroplanner.db` to `armillarylab.db` file rename, which is reversible by renaming back.
- All work is on a feature branch until you confirm the smoke test passes; if anything looks wrong, abandon the branch and `main` is untouched.
- The GitHub redirect (Phase 8) is durable - no urgency to update remotes the same day.
- No live PostgreSQL data is touched anywhere in this plan; only PG defaults, configs, and docs are renamed. Future PG deployments are unaffected and can opt into either the new defaults or the existing names via `DATABASE_URL`.
