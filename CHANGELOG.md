# Changelog

All notable changes to ArmillaryLab will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Project rename**: Versions 1.0.0 and 2.0.0 shipped under the previous project name **AstroPlanner**. The project was renamed to **ArmillaryLab** in 2026 to avoid conflict with an unrelated existing product. Historical version labels in this file refer to the project's name at the time of release.

## [Unreleased]

_Nothing yet._

---

## [2.7.4] - 2026-06-12

### Fixed

- **Imaging Logs nav link broken** — `@app.route("/imaging-logs")` decorator was accidentally dropped when the `mosaic_log` route was inserted above it in v2.7.3, causing a `BuildError` on every page that uses `base.html`. Decorator restored.

---

## [2.7.3] - 2026-06-12

### Added

- **Mosaic session log page** (`/mosaic/<id>/log`) — aggregated imaging & calibration log across all panels in a mosaic group, styled like the per-target imaging log.
  - Groups sessions by date; within each date, panels are listed with their panel number badge (P1, P2 …) and a link to the individual target page.
  - Edit and delete buttons on every session and calibration entry work identically to the per-target log.
  - Summary stats bar: imaging nights, panel count, total light sessions, total light time.
  - "Session Log" button added to the mosaic detail header.

### Fixed

- **Dashboard Mosaics block text contrast** — completion %, done/planned time, and description sub-text were using `text-muted` which is near-invisible on `table-dark`; replaced with `text-light` and explicit `rgba(255,255,255,x)` values.

---

## [2.7.2] - 2026-06-11

### Fixed

- **Dashboard Mosaics block** — completion %, done/planned time, and description rendered nearly invisible (`text-muted` on `table-dark`); replaced with legible `text-light` and inline `rgba` values.

---

## [2.7.1] - 2026-06-11

### Added

- **RA/Dec coordinate input flexibility** — the New/Edit Target form now accepts HMS (`20h 44m 00s`, `20:44:00`) and DMS (`+41° 16' 07"`, `+41:16:07`) in addition to decimal hours/degrees. A live preview converts between formats as you type; values are normalised to decimal on submit.
- **Mosaic quick-log card** — "Log Session to Panel" card on the mosaic overview page allows logging imaging progress to any non-archived panel without navigating into the panel. Channels are dynamically populated from the selected panel's plan.

### Fixed

- **Mosaic quick-log channel dropdown not populating** — `data-channels` HTML attribute encoding broke `JSON.parse`; replaced with a server-side `PANEL_CHANNELS` JS object map.
- **Mosaic quick-log form submission** — `next` redirect and `channel` field name routing corrected.
- **Text contrast in mosaic tables** — `text-muted` class is near-invisible on `table-dark`; replaced throughout Channel Progress and Panels tables with explicit `rgba(255,255,255,x)` and `text-light`.
- **Archived panel row readability** — `table-success` rows in the Panels table now use dark text overrides so content is legible.

### Changed

- Channel Progress totals table now shows HMS (`H:MM:SS`) alongside minutes for Done, Planned, and Remaining columns.

---

## [2.7.0] - 2026-06-11

### Added

- **Mosaic Groups** — group any set of panel targets under one named mosaic project.
  - New `MosaicGroup` model (`mosaic_groups` table): `name`, `description`, `panel_count_goal`, `notes`, `created_at`.
  - Two new nullable columns on `Target`: `mosaic_group_id` (FK → `mosaic_groups.id`) and `mosaic_panel_number` (integer, 1-based ordering). Both added via `apply_additive_schema_migrations()` on startup — no manual migration needed.
  - Five new routes: `GET /mosaics`, `GET|POST /mosaic/new`, `GET /mosaic/<id>`, `GET|POST /mosaic/<id>/edit`, `POST /mosaic/<id>/delete`, plus `POST /mosaic/<id>/update-notes` (AJAX inline edit).
  - **Mosaic detail page** (`mosaic_detail.html`): "Tonight's Panel" recommendation card (reuses priority-score logic), per-channel aggregate progress table with Bootstrap progress bars (total planned/done/remaining across all active panels), and an ordered panel grid showing per-panel completion %, per-channel done/planned, and status badges (Completed/In Progress/Started).
  - **Mosaic list page** (`mosaic_list.html`): table of all groups with completion bars and panel counts.
  - **Mosaic form** (`mosaic_form.html`): shared create/edit form.
  - **Dashboard integration**: compact "Mosaics" summary section on `/` (visible only when groups exist) with per-group completion bars; "Mosaics" nav link in `base.html`.
  - **Target form** (`target_form.html`): "Mosaic Group" dropdown and "Panel Number" input added to the New/Edit Target form; panel number field shows/hides via JS.
  - **Dashboard badge**: active targets that belong to a mosaic group show a small blue badge (`P3 · Cygnus Loop Mosaic`) linking to the mosaic detail page.
  - Delete mosaic group unlinks all panels (sets FK to NULL) rather than cascading — panels are preserved as standalone targets.

### Fixed / Performance

- **Dashboard load time (~10× faster)** — `compute_target_window()` was running a 61-point altitude + `get_body('moon', …)` loop for every active target on every page load. Added `skip_profile=False` parameter: when `True`, the loop runs 12 steps with no moon position calls (saves ~90% of per-target compute). Applied to `index()`, `mosaic_detail()` tonight's-panel loop, `export_nina_v2()` window-end calculation, and `api_conditions()`.
- Added a 10-minute process-level TTL cache for `skip_profile=True` results, keyed on target coordinates + observer location — rapid re-renders are near-instant after first computation.

### Migration

- `apply_additive_schema_migrations()` creates `mosaic_groups` table (via `db.create_all()`) then adds `targets.mosaic_group_id` (INTEGER FK) and `targets.mosaic_panel_number` (INTEGER) if not present. Both are nullable; existing targets are unaffected.

---

## [2.6.0] - 2026-06-01

### Added

- **NINA V2 Advanced Sequence export** — replaces the old single-click V1 export with a full modal dialog and a new JSON builder targeting NINA's Advanced Sequencer format.
  - New `nina_template_v2.json` base template: `DeepSkyObjectContainer` with complete session setup — `CoolCamera` (−10 °C), `StartGuider`, `CenterAndRotate`, `AutofocusAfterSetTime`, `TimeCondition` stop guard, and per-channel `SequentialContainer` capture blocks with `SwitchFilter`, `TakeExposure`, and `Dither` trigger wired up.
  - New backend route `POST /target/<id>/export_nina_v2` accepting: sequence name, DSO container name, position angle, cooldown duration, force-guider-calibration flag, dither-after-N, export mode (`all` / `single` / `zip`), per-channel gains (JSON), and an experimental `use_exposure_offset` flag.
  - Three export modes: **All channels** (single `.json`), **Single channel** (one `.json`), **Separate files** (`.zip` with one file per channel).
  - `$id`/`$ref` renumbering engine (`_resequence_subtree`) correctly handles multi-channel exports — internal references within each cloned channel block are remapped; external parent refs are left intact.
  - `build_nina_sequences_v2` / `build_nina_sequence_v2` builder functions in `nina_integration.py`.

- **Export NINA Sequence dialog** (`#ninaExportModal` in `target_detail.html`): sequence info, framing/setup controls, export-mode radio with channel picker, per-channel gain table (JS-populated from plan data with global-gain propagation), window end-time display, and experimental ExposureCount-offset checkbox.

- **Gain and sensor cooling on imaging sessions** — `ImagingSession` model gains two new optional columns:
  - `gain` (INTEGER) — sensor gain used during the session.
  - `sensor_cooling` (FLOAT) — actual achieved camera temperature in °C.
  - Both columns are added via `apply_additive_schema_migrations()` on startup (safe for existing databases).
  - **Add Imaging Progress** form and **Edit Session** form now expose these fields.
  - Session log rows show small `G<n>` and `<n>°C` badges when values are present.

- **Per-session gain/cooling in AstroBin CSV export** — `build_astrobin_export_rows` now stores per-session `gain` and `sensor_cooling` on each row. The CSV writer uses the per-session value when available, falling back to the modal's uniform form value. The non-tracked sessions path also captures these values while grouping.

- **AstroBin modal pre-population** — gain and cooling inputs default to values from the most-recent session that has them logged, with a "from last session" hint label.

### Removed

- `GlobalConfig.default_calibration_two_point` and `Target.override_calibration_two_point` read/write paths (columns retained for safe downgrade as noted in v2.5.0 deprecation notice).

### Migration

- `apply_additive_schema_migrations()` adds `imaging_sessions.gain` (INTEGER) and `imaging_sessions.sensor_cooling` (REAL/FLOAT) if not present. No data loss; existing rows get NULL for both columns.

---

## [2.5.0] - 2026-05-25

### Changed

- **Calibration suggestions are now end-of-channel only.** The v2.2.0 "two-point" workflow pinged users at 50% channel light progress to log half their flats, with the remainder due at end-of-channel. ArmillaryLab is a tracker, not a stacker — it never applies or averages flats — so forcing a mid-channel capture rhythm imposed workflow without improving stack quality. v2.5.0 fires a single suggestion per channel/frame-type when the channel's light frames complete and frames are still owed. *When* and *how* you capture (per-session, end-of-run, or any mix) is now entirely your call.
- `checkpoint` on each `CalibrationCapture` is now treated as free-form metadata; the log endpoint, the edit form, and the manual-log dropdown all still accept `midpoint`, `end`, and `manual` for backward compatibility, plus any tag clients send via the API. The suggestion engine no longer reads it as workflow state.
- The `/target/<id>/calibration/skip` endpoint now accepts `checkpoint="end"` only (rejects `midpoint` with HTTP 400).
- `get_effective_calibration_config()` no longer emits `two_point` in its payload, and `/api/target/<id>/calibration` follows suit. No first-party UI consumed the field; verify any external integrations.
- Rewrote [docs/CALIBRATION_GUIDE.md](docs/CALIBRATION_GUIDE.md) around the "tracking, not processing" framing.

### Removed

- The **"Use two-point flat capture by default"** checkbox on **Settings → Default Calibration Frames**.
- The **"Two-point flat capture"** override on **Target → Settings → Calibration Tracking**.
- `test_midpoint_suggestion_at_half_light_frames` and `test_skip_midpoint_end_includes_full_remainder` (replaced by `test_no_midpoint_suggestion_at_half_light_frames`, `test_calibration_suggestion_fires_only_at_channel_end`, `test_skip_calibration_rejects_midpoint`, `test_calibration_log_preserves_midpoint_checkpoint_tag`, and `test_migration_clears_legacy_midpoint_skips`).

### Deprecated

- The `GlobalConfig.default_calibration_two_point` and `Target.override_calibration_two_point` columns are no longer read or written by any code path. They are retained in this release for safe downgrade; **scheduled for removal in v2.6** (see [docs/FEATURES_ROADMAP.md](docs/FEATURES_ROADMAP.md) §19).
- The `two_point` field on the `/api/target/<id>/calibration` JSON payload is gone. External clients still depending on it should pin to v2.4.x or update.

### Migration

- `apply_additive_schema_migrations()` (runs on startup) now performs a one-time idempotent `DELETE FROM calibration_checkpoint_skips WHERE checkpoint = 'midpoint'` to clear stale skip rows that would otherwise be orphaned (no UI path remains to manage them).
- Existing `CalibrationCapture` rows with `checkpoint = 'midpoint'` are **left untouched** — historical capture metadata is preserved.

---

## [2.4.4] - 2026-05-25

### Fixed

- **5-day Forecast tab: seeing column no longer silently empty for targets with short imaging windows.** v2.4.2 added a nearest-7Timer-point fallback to `_aggregate_window_astro()` (Overview tab "Imaging Window Seeing" block) but the 5-day Forecast tab had its own independent seeing-aggregation loop inside `compute_forecast_days()` that still required points to fall strictly inside the window. For targets like Eastern Veil / C 33 with a packup-time-clipped window of ~84 min that landed between 7Timer's 3-hour grid points, every future night's Seeing cell showed "--" while wide-window targets like M 101 showed real values — a confusing inconsistency.

### Changed

- Extracted the nearest-neighbor fallback into a shared helper `_collect_seeing_points_for_window()` and reused it from both `_aggregate_window_astro()` and `compute_forecast_days()`. The helper caps the fallback distance to ~1.6 h (slightly more than half of 7Timer's 3-hour grid) so nights beyond 7Timer's ~72 h horizon still correctly render as empty rather than reaching backwards for stale data.
- Expanded `tests/test_conditions_window_astro.py` to cover the shared helper, the fallback-distance cap, and the forecast path (5 tests total).

---

## [2.4.3] - 2026-05-25

### Fixed

- **Night Conditions → Seeing tab: "your target" highlight now works for multi-word target types.** The backend sends `target_type` as snake_case strings (`supernova_remnant`, `emission_nebula`, `planetary_nebula`, etc.) while the client-side `SEEING_TYPES` lookup table used spaced labels (`"Supernova Remnant"`, ...). The lookup compared lowercased strings only, so the underscore mismatch silently broke matching for every multi-word type — the target-type callout fell back to the grey "no threshold defined for this type" message and the per-row "◀ your target" tag never appeared. Single-word types like `galaxy` happened to work, masking the bug. The Seeing tab now normalises both sides of the comparison by lowercasing and replacing underscores with spaces. The verdict callout (good / marginal / poor) and the per-row highlight both work for every type in the taxonomy.

---

## [2.4.2] - 2026-05-25

### Fixed

- **Night Conditions: Imaging-Window Seeing block no longer disappears for short windows.** 7Timer publishes seeing and transparency on a fixed 3-hour UTC grid. When a target's effective imaging window (after packup-time clipping) was shorter than ~3 hours and landed entirely between two grid points, `_aggregate_window_astro()` returned `None` and the template silently dropped the whole Seeing section in the right column of the Night Conditions panel — even though the "Right Now" Seeing block continued to render. The aggregator now falls back to the single 7Timer point closest to the window midpoint when no points fall strictly inside the window, and exposes a `nearest_fallback` flag on the payload. Added regression tests in `tests/test_conditions_window_astro.py`.

---

## [2.4.1] - 2026-05-25

### Fixed

- **Plan editor: per-channel manual time overrides are now preserved on Save.** Previously, if the user changed both the master total integration time and one or more per-channel minutes in the same Save Plan submit, the backend would silently discard the per-channel edits and proportionally rescale the prior channel ratios to fit the new total instead. This caused user-specified splits like H=20h / O=20h / S=30h on a 70h total to be saved back as H=35h / O=21h / S=14h. The `update_plan` route now always honors per-channel `ch_*_minutes` form values, with the proportional rescale acting only as a baseline for channels left unspecified. Added regression test `test_update_plan_per_channel_overrides_win_over_master_total`.

---

## [2.4.0] - 2026-05-25

### Version 2.4.0 - Comprehensive Object Resolver

**ArmillaryLab v2.4.0** introduces a unified object-resolution stack that turns any astronomical designation (NGC, IC, Messier, Caldwell, nickname, SIMBAD ID, …) into a canonical name, J2000 coordinates, object type, magnitude, and cross-catalog aliases — offline-first, with network fallbacks for the long tail.

### Added

- **Resolver chain (first-hit-wins)**: New `resolver/` package wiring `local_catalog` → `simbad` → `ned` → `vizier` → `sesame`, each with a confidence score. Bundled NGC/IC, Messier, Caldwell, and nickname catalogs make the common cases instant and fully offline; network sources fill the long tail.
- **DB-backed resolver cache**: New `resolver_cache` table with 90-day positive / 1-day negative TTL. Migration is additive and runs automatically on startup.
- **Bidirectional cross-catalog aliases**: `C 33` ↔ `NGC 6992`, `M 31` ↔ `NGC 224`, `NGC 7000` ↔ `Caldwell 20`, etc. Both the confirmation modal and the resolver badge display cross-catalog IDs as "Also catalogued as …" alongside common-name nicknames.
- **ObjectMapping integration**: Manual user mappings now layer cleanly on top of the resolver chain.
- **Resolver API + UI**: `/api/resolve` returns canonical name, RA/Dec, object type, magnitude, common names, and cross-catalog designations. Target form shows a confirmation modal with a one-click "use canonical name" option and a resolver badge under the name field.
- **Resolver settings, health, CLI**: New Settings panel for toggling individual network sources and tuning TTLs, `GET /api/resolve/health` endpoint with per-source status and cache stats, and `flask resolver-test "<name>"` CLI for offline debugging.
- **Unified `TargetType` taxonomy**: Eight canonical object types (emission, diffuse, reflection, galaxy, cluster, planetary, supernova_remnant, other) used consistently across the resolver, form, and database.

### Changed

- **SQLite sample data**: The repository commits **`armillarylab.db`** (project root) as a **demonstration dataset** (bundled presets, demo targets/sessions/calibration). `.gitignore` now ignores every `*.db` **except** that file so local clones get the showcase catalog by default.
- **Documentation**: Describes **Option A** (keep bundled DB + `migrate-db`) versus **Option B** (delete + `init-db` for blank). README, Database Guide, and Docker Guide updated accordingly.
- **`uploads/`**: Personal final astro images removed from revision control (folder ignored except **`uploads/.gitkeep`**). Bundled **`armillarylab.db`** no longer points sample targets at removed filenames.

---

## [2.3.0] - 2026-05-22

### Version 2.3.0 - Night Conditions: Seeing Guide & 5-Day Forecast

### Added

- **Seeing Guide** tab in the Night Conditions popup with educational context for seeing/transparency values.
- **5-Day Forecast** tab in the Night Conditions popup for at-a-glance multi-night planning.

---

## [2.2.0] - 2026-05-21

### Version 2.2.0 - Calibration Frames Management

**ArmillaryLab v2.2.0** adds optional per-target calibration frame tracking with global defaults, manual dark/bias logging, and two-point flat/dark-flat suggestions at channel midpoint and end.

### Added

#### Calibration Frame Tracking
- **Opt-in per target**: Enable calibration tracking on target settings; global defaults on Settings page
- **Frame types**: Darks and bias (manual logging); flats and dark flats per channel with optional two-point workflow
- **Two-point suggestions**: At 50% light frame progress, suggest half the flat/dark-flat count; remainder at channel completion
- **Skip/defer**: Skip midpoint or end checkpoints; end suggestion covers remaining counts; manual catch-up anytime
- **Action items**: Target detail banners with Log capture / Skip for now when thresholds are crossed
- **History**: Calibration captures grouped by date with edit/delete
- **API**: `GET /api/target/<id>/calibration` for status and suggestions JSON

#### New Models & Module
- `CalibrationCapture`, `CalibrationCheckpointSkip` tables
- `GlobalConfig` / `Target` calibration default and override columns
- `calibration_utils.py` — suggestion engine and status aggregation

### Changed

- **AstroBin export**: When calibration tracking is enabled, export modal prefills darks/flats/flatDarks/bias from captured totals (still overridable)
- **`flask migrate-db`**: Adds calibration columns to existing SQLite databases and creates new tables

### Notes

- Run `flask migrate-db` after upgrading if you use an existing SQLite database.
- Clone target copies calibration **settings** only, not capture history or skip records.

## [2.1.0] - 2026-05-16

### 🎉 Version 2.1.0 - Night Conditions & Intelligent Channel Suggestion

**ArmillaryLab v2.1.0** adds real-time night conditions awareness with moon phase tracking, weather and astronomical seeing integration, and an intelligent channel suggestion engine -- all accessible from a single navbar icon.

### Changed

- Renamed the project from **AstroPlanner** to **ArmillaryLab** across code, config, Docker, documentation, and the SQLite database file (`astroplanner.db` to `armillarylab.db`).
- Updated default PostgreSQL DB name and role to `armillarylab` in [config/database.py](../config/database.py); existing PG deployments can keep using their current names by setting `DATABASE_URL` explicitly.
- Updated Docker Compose service/container names and PostgreSQL service defaults.
- Updated the GitHub repository URL references in `README.md`.

### Added

#### Night Conditions Popup
- **Moon phase overlay**: Current moon phase with emoji, illumination percentage, and next full moon countdown — computed offline via astroplan
- **Weather integration**: Temperature, humidity, cloud cover, and wind data from Open-Meteo API (free, no key required)
- **Astronomical seeing**: Seeing quality and transparency ratings from 7Timer API (free, no key required)
- **Channel suggestion engine**: Weighted scoring algorithm recommending the best filter channel based on moon suitability and remaining plan progress
  - `score = moon_weight * remaining_ratio` — Ha strongest (1.0 at full moon), OIII weakest (0.3), broadband (0.2)
- **Imaging window forecast**: Two-column layout showing current conditions alongside aggregated imaging window weather and seeing
- **3-tier offline fallback**: Online → cached 5-day forecast → offline moon-only → status message
- **Gmail-style navbar popup**: Dark-themed overlay card with Live/Cached/Offline status badge
- **Target-aware**: Shows channel suggestion when viewing a target, general conditions on other pages

#### New Files
- `conditions_utils.py` — Moon computation, weather/seeing API clients, caching, and channel scoring logic

### Notes

- No data migration required; the SQLite file rename preserves all data unchanged.
- No new Python dependencies — uses existing astropy/astroplan + stdlib urllib
- The GitHub redirect from the old repo URL keeps existing remotes working until they are updated with `git remote set-url`.

## [2.0.0] - 2026-02-01

### 🎉 Version 2.0.0 - PostgreSQL Support & Equipment Management

**AstroPlanner v2.0.0** (released under the project's previous name) is a major release introducing PostgreSQL database support for production deployments, comprehensive filter and filter wheel management, target archiving, and enhanced astronomy chart features.

### ✨ Major New Features

#### PostgreSQL Database Support
- **Dual Database Engine**: Runtime selection between SQLite (development) and PostgreSQL (production)
- **Automated Migration Tool**: Seamless bidirectional data migration between SQLite ↔ PostgreSQL
- **Connection Pooling**: Optimized PostgreSQL connection pooling for production workloads
- **Cloud-Ready**: Designed for deployment on Heroku, Railway, Render, and other cloud platforms
- **Environment Configuration**: Flexible `.env` file based configuration with sensible defaults

#### Filter & Filter Wheel Management
- **Filter Database**: Comprehensive filter management with types (narrowband, broadband, other)
- **Filter Wheels**: Multi-wheel support with slot configuration and NINA profile mapping
- **AstroBin Integration**: Filter AstroBin IDs for equipment CSV export compatibility
- **Bulk Updates**: Apply filter presets (generic, ZWO) with automatic AstroBin ID population

#### Target Archive System
- **Archive Completed Targets**: Mark finished projects as complete with notes
- **Clone Targets**: Duplicate archived targets to start new imaging projects
- **Archive View**: Separate view for completed/archived targets with restoration capability
- **Completion Tracking**: Record completion date and notes for project history

#### Enhanced Astronomy Charts
- **Moon Altitude Curve**: Visualize moon altitude alongside target altitude
- **Moon Rise/Set Indicators**: Clear markers showing moon visibility windows
- **Meridian Flip Marker**: Visual indicator for German Equatorial Mount flip timing
- **Improved Legend**: Better chart organization and readability

### 🔧 Improvements

#### Database Management CLI
- `flask db info` - Display current database configuration and status
- `flask db migrate` - Automated migration with 5-step workflow:
  1. Test target connection
  2. Initialize target schema
  3. Clear target data (with confirmation)
  4. Migrate all data
  5. Update `.env` file automatically
- `flask db backup` - Create timestamped database backups
- `flask init-db --force` - Clean database re-initialization

#### UI/UX Improvements
- **Fixed Text Visibility**: Page subtitles now use `text-info` for better dark theme visibility
- **Button Contrast**: Edit buttons use `btn-outline-secondary` for consistent visibility
- **Archived Targets Section**: Clear visual separation with improved button styling

#### Documentation
- **DATABASE_GUIDE.md**: Comprehensive guide for SQLite and PostgreSQL setup
- **DEPLOYMENT_SECURITY_PLAN.md**: Security considerations for production deployment
- **POSTGRESQL_DEPLOYMENT.md**: Step-by-step cloud deployment guide
- **Updated README**: Added configuration file documentation

### 🐛 Bug Fixes

- Fixed SQLAlchemy 2.0 count query syntax in migration tool
- Fixed `init-db --force` to properly drop all tables before recreation
- Fixed filter wheel edit button visibility (btn-outline-light → btn-outline-secondary)
- Fixed migration schema validation to check table existence
- Fixed test imports to match actual module API

### 📋 Technical Details

#### New Dependencies
- `psycopg2-binary` - PostgreSQL adapter for Python
- `python-dotenv` - Environment file management (already included)

#### Database Schema Changes
- Added `is_archived`, `archived_at`, `completion_notes` columns to targets table
- Added `astrobin_id` column to filters table
- New tables: `filter_wheels`, `filter_wheel_slots`, `palette_filters`

#### Configuration Files
- `.env.example` - Template for development configuration
- `.env.production` - Template for production PostgreSQL configuration
- `.flaskenv` - Flask server settings (auto-loaded)

### 📝 Migration from v1.0.0

1. **Backup your database**: `flask db backup`
2. **Update dependencies**: `pip install -r requirements.txt`
3. **Initialize new schema**: `flask init-db` (preserves existing data for SQLite)
4. **Optional PostgreSQL migration**: See DATABASE_GUIDE.md

### 🔒 License Change

- Changed from Apache 2.0 to MIT License for broader compatibility

---

## [1.0.0] - 2025-12-27

### 🎉 Version 1.0.0 - Complete Feature Set Release

**AstroPlanner v1.0.0** (released under the project's previous name) represents a mature, feature-complete astrophotography planning platform with comprehensive target management, session tracking, telescope integration, and advanced progress management capabilities.

### ✅ Complete Feature Set

#### Target Management & Planning
- **Project-based Organization**: Each target treated as its own imaging project with dedicated tracking
- **Creation Tracking**: Automatic timestamp tracking with robust local timezone support  
- **Target Settings**: Per-target overrides for pack-up time and minimum altitude constraints
- **Priority Scoring**: Intelligent priority calculation based on completion percentage, remaining time, and tonight's window
- **Advanced Filter System**: Custom filter addition with real-time bidirectional calculations (minutes ↔ frames ↔ exposure time)
- **NINA Filter Mapping**: Custom filters map to standard telescope filter wheel names for hardware compatibility

#### Session Planning & Execution
- **Tonight's Recommendation**: AI-driven target recommendations with intelligent priority scoring
- **Window Calculations**: Automatic imaging window calculation based on sunset, astronomical darkness, and altitude constraints
- **Enhanced Progress Tracking**: Comprehensive session tracking with edit/delete functionality and data validation
- **Advanced Time Management**: Flexible H:M:S formatting with bidirectional conversions and decimal precision support
- **Imaging Logs**: Complete session history with statistics, analytics, monthly summaries, and backdating support

#### Palette & Filter Management
- **Database-driven Palettes**: Full CRUD operations with system vs. custom palette protection and JSON-based storage
- **Auto-populated Filters**: Filter selection automatically populates from active target plans with custom filter support
- **Smart Filter Recommendations**: Intelligent filter suggestions based on target type and palette selection
- **Custom Filter Integration**: On-the-fly custom filter addition with auto-save and NINA telescope compatibility

#### Advanced Planning & Calculations  
- **Real-time Bidirectional Inputs**: Frame counts ↔ exposure times ↔ total minutes with decimal precision support
- **Dynamic Calculations**: Real-time JavaScript validation and calculation updates as you modify exposure plans
- **Multi-format Display**: Times displayed in both minutes and H:M:S format throughout the interface
- **Status Indicators**: Visual badges and progress indicators showing completion status and tonight's imaging potential
- **Column Organization**: Logical table column ordering for improved workflow efficiency

#### NINA Integration & Telescope Support
- **Advanced Export System**: Direct export to N.I.N.A. (Nighttime Imaging 'N' Astronomy) Advanced Sequencer
- **Filter Wheel Integration**: Custom filter mapping ensures proper telescope hardware operation and compatibility
- **Template System**: Customizable sequence templates with dynamic block generation
- **Remaining Frames Export**: Intelligent export of only remaining frames for efficient session continuation
- **Hardware Compatibility**: Full support for telescope filter wheels, cameras, and automation systems

#### Configuration & Global Settings
- **Observer Location**: Configurable latitude, longitude, and elevation with global defaults and validation
- **Timezone Support**: Robust timezone handling with Windows compatibility and automatic UTC conversion
- **Settings Management**: Dedicated configuration interface for both global and per-target settings
- **Default Overrides**: Global defaults with per-target override capabilities for flexible configuration

#### Data Management & Session Analytics
- **Session CRUD Operations**: Complete edit and delete functionality for imaging sessions with confirmation dialogs
- **Comprehensive Analytics**: Daily, monthly, and overall imaging statistics with visual progress indicators
- **Session History**: Complete imaging session tracking with date grouping and chronological organization
- **Data Integrity**: Form validation, error handling, UTF-8 encoding, and database consistency maintenance
- **Progress Visualization**: Charts, summaries, and visual indicators for session tracking and planning

#### Technical Excellence
- **Bootstrap Integration**: Fresh Bootstrap 5.3.2 and Bootstrap Icons 1.11.3 with proper asset integrity
- **Responsive Design**: Mobile-friendly interface with collapsible sections and space-efficient design
- **Form Validation**: HTML5 validation with JavaScript enhancement and selective auto-save functionality
- **Error Handling**: Comprehensive error handling with proper encoding and robust template management
- **Database Architecture**: SQLAlchemy-based models with JSON storage and efficient relationship management

### 🔧 Technical Improvements
- **Filter Recommendations**: Smart filter recommendations based on target type

#### Time Management & Planning
- **H:M:S Time Formatting**: Flexible time input and display in both minutes and H:M:S format
- **Bidirectional Frame/Time Inputs**: Change frame counts to update exposure times and vice versa
- **Real-time Calculations**: Dynamic updates as you modify exposure plans
- **Multi-format Display**: Times shown in both minutes and H:M:S throughout the interface

- **Fresh Bootstrap Assets**: Updated to Bootstrap 5.3.2 and Bootstrap Icons 1.11.3 with proper asset integrity
- **JavaScript Error Resolution**: Fixed Bootstrap JavaScript corruption and undefined reference errors
- **Template Encoding**: Proper UTF-8 encoding for all templates with comprehensive error handling
- **Database Model Updates**: Enhanced models for session editing and custom filter support
- **Route Architecture**: New `/session/<id>/edit` and `/session/<id>/delete` routes with proper validation

### 🔄 Migration from Previous Versions
- **Database Compatibility**: Maintains backward compatibility with existing data
- **Asset Updates**: Fresh Bootstrap assets resolve display issues and JavaScript errors
- **Template Updates**: Enhanced templates with improved encoding and functionality
- **Configuration Preservation**: All existing settings and data remain intact

### 🎯 Future Development

Version 1.0.0 establishes the foundation for future enhancements:
- **PostgreSQL Support**: Planned for v2.0 to enable cloud deployment capabilities
- **AI Session Recommendations**: Weather integration and machine learning-driven session optimization
- **Mobile Optimization**: Enhanced mobile interface for field use
- **Additional Observatory Integrations**: Support for more telescope control software

### 📝 Documentation

- **Complete Feature Roadmap**: Comprehensive documentation of all implemented features
- **Updated README**: Detailed feature list and quick start guide
- **Version Tracking**: Proper semantic versioning with VERSION file
- **Change Documentation**: Complete changelog with feature details and technical improvements

---

## Previous Development History

### Core Foundation (December 2025)
- **Target Management System**: Project-based target organization with creation tracking
- **Session Planning**: Tonight's recommendations with window calculations  
- **Palette Management**: Database-driven custom palette system
- **NINA Integration**: Advanced Sequencer export with template support
- **Global Configuration**: Observer location and settings management
- **Altitude Charts**: Visual planning tools with threshold indicators and window shading
- **Progress Tracking**: Comprehensive imaging session logging with statistics
- **Custom Filter System**: Real-time calculations with NINA mapping support

### Technical Foundation
- **Flask Architecture**: Modern Python web framework with SQLAlchemy ORM
- **Astronomical Computing**: Astropy and Astroplan integration for professional calculations
- **Database Design**: Comprehensive models with foreign key relationships and data integrity
- **Responsive UI**: Bootstrap-based interface optimized for desktop planning workflows
- **Windows Compatibility**: Robust timezone handling and path management

#### Interface Design
- **Dark Theme**: Optimized for nighttime use with astronomy-friendly color scheme
- **Intuitive Navigation**: Clear workflow from target creation to session planning
- **Real-time Feedback**: Immediate updates as settings and plans are modified
- **Professional Appearance**: Charts and visualizations suitable for serious astrophotography

#### Workflow Optimization
- **Streamlined Target Creation**: Quick setup with intelligent defaults
- **Efficient Session Planning**: Prioritized recommendations with visual planning aids
- **Progress Tracking**: Clear indicators of completion status and remaining work
- **Export Integration**: Seamless transition from planning to observatory execution

### 📊 Statistics
- **8 Major Features** implemented and completed
- **1,400+ lines** of Python application code
- **680+ lines** of HTML template code with advanced JavaScript functionality  
- **270+ lines** of comprehensive roadmap documentation
- **240+ lines** of professional README documentation
- **Extensive testing** on Windows Python 3.14 environment

### 🔧 Dependencies
- Python 3.14+ (tested on 3.14.2)
- Flask 3.0.3 web framework
- SQLAlchemy 2.0.32 database ORM
- Astropy ≥7.2.0 for astronomical calculations
- Astroplan ≥0.10.1 for observation planning
- NumPy ≥2.3.5 for numerical computations
- Chart.js for interactive altitude visualization

### 📝 Documentation
- Comprehensive README with installation and usage instructions
- Detailed feature roadmap with implementation status
- Professional project structure and development guidelines
- Docker support for containerized deployment
- License and contribution guidelines

---

**Release Notes**: This stable release provides a complete astrophotography planning solution suitable for serious amateur astronomers and astrophotographers. All core features are implemented, tested, and ready for production use.

**Next Release Focus**: Future versions will focus on advanced features like AI-driven session recommendation engines, weather integration, and enhanced mobile responsiveness.