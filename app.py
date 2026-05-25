import csv
import click

from datetime import datetime, time, timezone, timedelta
import os
import io
import json
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_from_directory, jsonify,
    send_file, g
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import relationship
from werkzeug.utils import secure_filename

from astro_utils import (
    compute_target_window,
    build_default_plan_json,
)

from nina_integration import load_nina_template, build_nina_sequence_from_blocks
from time_utils import register_time_filters, format_hms, parse_hms, hms_to_minutes
from calibration_utils import (
    get_calibration_payload,
    aggregate_calibration_for_export,
    resolve_astrobin_calibration_columns,
    build_astrobin_export_rows,
    build_target_imaging_log_days,
    build_global_imaging_log_days,
    calibration_log_stats,
    format_suggestion_flash,
    channel_calibration_badges,
)
from zoneinfo import ZoneInfo

# Import database configuration
from config.database import get_flask_config
from config.sqlite_health import (
    check_sqlite_database,
    sqlite_has_core_schema,
)

from config.flask_process import (
    is_flask_serving_process,
    should_open_live_sqlite,
)

# Import CLI commands
from cli import register_cli_commands

# Application version
APP_VERSION = "2.5.0"
APP_NAME = "ArmillaryLab"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

# Make version info available to all templates
@app.context_processor
def inject_version():
    return {
        'app_version': APP_VERSION,
        'app_name': APP_NAME,
        'datetime': datetime
    }

# --- Database configuration with PostgreSQL support ----------------------
flask_config, db_config = get_flask_config(BASE_DIR)
app.config.update(flask_config)

if os.environ.get("TESTING", "").lower() in ("1", "true", "yes"):
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

db = SQLAlchemy(app)


def _register_sqlite_pragmas(engine, db_configuration):
    if db_configuration.db_type != "sqlite":
        return
    from sqlalchemy import event

    pragmas = db_configuration.sqlite_connect_pragmas()

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        for key, value in pragmas:
            cursor.execute(f"PRAGMA {key}={value}")
        cursor.close()


def _register_sqlite_shutdown():
    """Release SQLite file handles when the dev server or a reload child exits."""
    import atexit

    def _dispose():
        if not is_flask_serving_process():
            return
        try:
            db.session.remove()
            db.engine.dispose()
        except Exception:
            pass

    atexit.register(_dispose)


def apply_additive_schema_migrations(log=print):
    """Apply idempotent additive schema updates. Safe to call on every startup."""
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    if "targets" not in inspector.get_table_names():
        return []

    is_pg = db_config.db_type == "postgresql"
    bool_true = "DEFAULT TRUE" if is_pg else "DEFAULT 1"
    bool_false = "DEFAULT FALSE" if is_pg else "DEFAULT 0"
    float_type = "DOUBLE PRECISION" if is_pg else "REAL"

    applied = []

    def add_column_if_missing(table, column, ddl):
        if table not in inspector.get_table_names():
            return
        columns = [col["name"] for col in inspector.get_columns(table)]
        if column not in columns:
            with db.engine.connect() as conn:
                conn.execute(text(ddl))
                conn.commit()
            applied.append(f"{table}.{column}")
            log(f"Added '{column}' column to {table} table.")

    if "filters" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("filters")]
        if "astrobin_id" not in columns:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE filters ADD COLUMN astrobin_id INTEGER"))
                conn.commit()
            applied.append("filters.astrobin_id")
            log("Added 'astrobin_id' column to filters table.")

    for col, ddl in (
        ("default_calibration_darks", "ALTER TABLE global_config ADD COLUMN default_calibration_darks INTEGER DEFAULT 0"),
        ("default_calibration_flats_per_channel", "ALTER TABLE global_config ADD COLUMN default_calibration_flats_per_channel INTEGER DEFAULT 0"),
        ("default_calibration_dark_flats_per_channel", "ALTER TABLE global_config ADD COLUMN default_calibration_dark_flats_per_channel INTEGER DEFAULT 0"),
        ("default_calibration_bias", "ALTER TABLE global_config ADD COLUMN default_calibration_bias INTEGER DEFAULT 0"),
        ("default_calibration_two_point", f"ALTER TABLE global_config ADD COLUMN default_calibration_two_point BOOLEAN {bool_true}"),
        ("max_cloud_cover_pct", "ALTER TABLE global_config ADD COLUMN max_cloud_cover_pct INTEGER DEFAULT 25"),
        # Resolver settings (Phase 8)
        ("resolver_enable_simbad", f"ALTER TABLE global_config ADD COLUMN resolver_enable_simbad BOOLEAN {bool_true}"),
        ("resolver_enable_ned",    f"ALTER TABLE global_config ADD COLUMN resolver_enable_ned BOOLEAN {bool_true}"),
        ("resolver_enable_vizier", f"ALTER TABLE global_config ADD COLUMN resolver_enable_vizier BOOLEAN {bool_true}"),
        ("resolver_enable_sesame", f"ALTER TABLE global_config ADD COLUMN resolver_enable_sesame BOOLEAN {bool_true}"),
        ("resolver_offline_mode",  f"ALTER TABLE global_config ADD COLUMN resolver_offline_mode BOOLEAN {bool_false}"),
        ("resolver_cache_ttl_days","ALTER TABLE global_config ADD COLUMN resolver_cache_ttl_days INTEGER DEFAULT 90"),
    ):
        add_column_if_missing("global_config", col, ddl)

    # ResolverCache: additive column for cross-catalog aliases.
    add_column_if_missing(
        "resolver_cache",
        "catalog_aliases_json",
        "ALTER TABLE resolver_cache ADD COLUMN catalog_aliases_json TEXT",
    )

    for col, ddl in (
        ("calibration_tracking_enabled", f"ALTER TABLE targets ADD COLUMN calibration_tracking_enabled BOOLEAN {bool_false}"),
        ("override_calibration_darks", "ALTER TABLE targets ADD COLUMN override_calibration_darks INTEGER"),
        ("override_calibration_flats_per_channel", "ALTER TABLE targets ADD COLUMN override_calibration_flats_per_channel INTEGER"),
        ("override_calibration_dark_flats_per_channel", "ALTER TABLE targets ADD COLUMN override_calibration_dark_flats_per_channel INTEGER"),
        ("override_calibration_bias", "ALTER TABLE targets ADD COLUMN override_calibration_bias INTEGER"),
        ("override_calibration_two_point", "ALTER TABLE targets ADD COLUMN override_calibration_two_point BOOLEAN"),
    ):
        add_column_if_missing("targets", col, ddl)

    add_column_if_missing(
        "calibration_captures",
        "sub_exposure_seconds",
        f"ALTER TABLE calibration_captures ADD COLUMN sub_exposure_seconds {float_type}",
    )

    db.create_all()

    # Ensure the 8 canonical TargetType rows exist (idempotent upsert).
    # This is the single source of truth used by detect_target_type(), the
    # palette recommender, and the resolver's SIMBAD type-mapper. Legacy
    # broad-type rows (e.g. "Galaxy", "Nebula") from old `cli.py db init`
    # installs are left untouched to preserve any ObjectMapping FK references.
    if "target_types" in inspector.get_table_names():
        canonical_types = [
            ("emission",           "SHO",  "Emission nebulae work excellently with narrowband SHO filters"),
            ("diffuse",            "HOO",  "Diffuse nebulae often benefit from HOO for enhanced contrast"),
            ("reflection",         "LRGB", "Reflection nebulae show great detail with broadband LRGB"),
            ("galaxy",             "LRGB", "Galaxies typically use broadband LRGB for star colors and detail"),
            ("cluster",            "LRGB", "Star clusters showcase natural colors best with LRGB"),
            ("planetary",          "SHO",  "Planetary nebulae reveal structure well with narrowband SHO"),
            ("supernova_remnant",  "SHO",  "Supernova remnants often have strong emission lines, perfect for SHO"),
            ("other",              "SHO",  "SHO is a versatile starting point for most deep sky targets"),
        ]
        try:
            inserted = 0
            for name, palette, description in canonical_types:
                existing = TargetType.query.filter_by(name=name).first()
                if existing is None:
                    db.session.add(TargetType(
                        name=name,
                        recommended_palette=palette,
                        description=description,
                    ))
                    inserted += 1
            if inserted:
                db.session.commit()
                applied.append(f"target_types(+{inserted} canonical)")
                log(f"Seeded {inserted} canonical TargetType rows.")
        except Exception as exc:
            db.session.rollback()
            log(f"WARNING: canonical TargetType seed skipped: {exc}")

    # v2.5.0 data cleanup: the two-point flat workflow was dropped, so any
    # historical "midpoint" skip rows are now noise. Idempotent — once the
    # rows are gone subsequent runs delete nothing.
    if "calibration_checkpoint_skips" in inspector.get_table_names():
        try:
            with db.engine.connect() as conn:
                result = conn.execute(text(
                    "DELETE FROM calibration_checkpoint_skips WHERE checkpoint = 'midpoint'"
                ))
                conn.commit()
                removed = result.rowcount or 0
            if removed > 0:
                applied.append(f"calibration_checkpoint_skips(-{removed} midpoint)")
                log(f"Removed {removed} legacy midpoint skip rows (v2.5.0 cleanup).")
        except Exception as exc:
            log(f"WARNING: legacy midpoint skip cleanup skipped: {exc}")

    if applied:
        log(f"Schema sync applied: {', '.join(applied)}")
    return applied


_serving_initialized = False


def _ensure_pg_schema_ready():
    """Run additive schema sync once for PostgreSQL on first request."""
    global _serving_initialized
    if _serving_initialized:
        return
    _serving_initialized = True
    if app.config.get("TESTING"):
        return
    try:
        applied = apply_additive_schema_migrations(log=app.logger.info)
        if applied:
            db.engine.dispose()
            db.session.remove()
    except Exception as exc:
        app.logger.warning("PostgreSQL startup schema sync skipped: %s", exc)


def ensure_sqlite_serving_ready():
    """
    Open and validate SQLite once per serving process.

    Must NOT run at import time — ``import app`` from helper scripts must not
    touch armillarylab.db while Flask is already running.
    """
    global _serving_initialized
    if _serving_initialized:
        return
    if db_config.db_type != "sqlite" or app.config.get("TESTING"):
        _serving_initialized = True
        return
    if not should_open_live_sqlite():
        return
    _register_sqlite_pragmas(db.engine, db_config)
    _init_sqlite_for_serving_process()
    _serving_initialized = True


def _init_sqlite_for_serving_process():
    if db_config.db_type != "sqlite" or app.config.get("TESTING"):
        return
    if not should_open_live_sqlite():
        return
    db_path = db_config.sqlite_file_path()
    if not db_path:
        return
    ok, msg, _info = check_sqlite_database(db_path, clean_sidecars=True)
    if not ok:
        app.logger.error("SQLite startup check failed: %s", msg)
        return
    if "Removed sidecars" in msg:
        app.logger.info("SQLite startup: %s", msg)
        db.engine.dispose()
        db.session.remove()
    applied = apply_additive_schema_migrations(log=app.logger.info)
    if applied:
        db.engine.dispose()
        db.session.remove()


_register_sqlite_shutdown()


def _check_sqlite_health() -> tuple[bool, str]:
    """Validate on-disk SQLite. Read-only — never removes sidecars or restores."""
    if db_config.db_type != "sqlite" or app.config.get("TESTING"):
        return True, ""
    if not should_open_live_sqlite():
        return True, ""
    db_path = db_config.sqlite_file_path()
    if not db_path:
        return True, ""
    if sqlite_has_core_schema(db_path):
        return True, ""
    ok, msg, _info = check_sqlite_database(db_path, clean_sidecars=False)
    if not ok:
        db.session.remove()
        db.engine.dispose()
        app.logger.error("SQLite unavailable: %s", msg)
    return ok, msg


@app.before_request
def _ensure_db_before_request():
    """Run startup schema sync and block requests when DB is unavailable."""
    if app.config.get("TESTING"):
        return
    if db_config.db_type == "postgresql":
        _ensure_pg_schema_ready()
        return
    if not should_open_live_sqlite():
        return
    ensure_sqlite_serving_ready()
    ok, msg = _check_sqlite_health()
    if ok:
        return
    if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
        return jsonify({"error": "Database unavailable", "detail": msg}), 503
    return render_template("db_unavailable.html", message=msg), 503


def _handle_missing_schema(e):
    """Shared handler for missing columns/tables across both SQLite and PostgreSQL."""
    if app.config.get("TESTING"):
        raise e
    err = str(getattr(e, "orig", e)).lower()

    missing_column = ("no such column" in err or
                      ("column" in err and "does not exist" in err))
    missing_table = ("no such table" in err or
                     ("relation" in err and "does not exist" in err))

    if not missing_column and not missing_table:
        raise e
    if missing_column and not getattr(g, "_schema_sync_attempted", False):
        g._schema_sync_attempted = True
        try:
            applied = apply_additive_schema_migrations(log=app.logger.info)
            if applied:
                db.session.remove()
                db.engine.dispose()
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Schema updated — please retry", "repaired": True}), 503
                return redirect(request.url), 302
        except Exception as sync_exc:
            app.logger.error("Schema sync failed: %s", sync_exc)
    if not missing_table:
        raise e
    if not getattr(g, "_db_recheck_attempted", False):
        g._db_recheck_attempted = True
        ok, msg = _check_sqlite_health()
        if ok:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Database recovered — please retry", "repaired": True}), 503
            return redirect(request.url), 302
        if request.path.startswith("/api/"):
            return jsonify({"error": "Database unavailable", "detail": msg}), 503
        return render_template("db_unavailable.html", message=msg), 503
    if request.path.startswith("/api/"):
        return jsonify({"error": "Database unavailable", "detail": err}), 503
    return render_template(
        "db_unavailable.html",
        message=(
            "Database schema error. If your code is newer than this database file, "
            "stop Flask and run flask migrate-db once. If you already match this version, "
            "restore from backup or diagnose with python scripts/diagnose_db.py."
        ),
    ), 503


@app.errorhandler(OperationalError)
def _handle_operational_error(e):
    """SQLite raises OperationalError for missing tables/columns."""
    return _handle_missing_schema(e)


@app.errorhandler(ProgrammingError)
def _handle_programming_error(e):
    """PostgreSQL raises ProgrammingError for missing tables/columns."""
    return _handle_missing_schema(e)


# Register CLI commands
register_cli_commands(app)

# Register time formatting filters
register_time_filters(app)

# --- Uploads config ---------------------------------------------------------
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB


# ---------------------------------------------------------------------------
# MODELS
# ---------------------------------------------------------------------------

class GlobalConfig(db.Model):
    __tablename__ = "global_config"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Observer location
    observer_lat = db.Column(db.Float, default=24.7136)  # Riyadh
    observer_lon = db.Column(db.Float, default=46.6753)
    observer_elev_m = db.Column(db.Float, default=600)
    
    # Default observation settings
    default_packup_time = db.Column(db.String(5), default="01:00")
    default_min_altitude = db.Column(db.Float, default=30.0)

    # Night conditions thresholds
    max_cloud_cover_pct = db.Column(db.Integer, default=25)

    # Default calibration frame counts (0 = disabled)
    default_calibration_darks = db.Column(db.Integer, default=0)
    default_calibration_flats_per_channel = db.Column(db.Integer, default=0)
    default_calibration_dark_flats_per_channel = db.Column(db.Integer, default=0)
    default_calibration_bias = db.Column(db.Integer, default=0)
    default_calibration_two_point = db.Column(db.Boolean, default=True)
    
    # Timezone
    timezone_name = db.Column(db.String(64), default="Asia/Riyadh")

    # Resolver settings (Phase 8)
    resolver_enable_simbad = db.Column(db.Boolean, default=True)
    resolver_enable_ned = db.Column(db.Boolean, default=True)
    resolver_enable_vizier = db.Column(db.Boolean, default=True)
    resolver_enable_sesame = db.Column(db.Boolean, default=True)
    resolver_offline_mode = db.Column(db.Boolean, default=False)
    resolver_cache_ttl_days = db.Column(db.Integer, default=90)

    # Tracking
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<GlobalConfig lat={self.observer_lat} lon={self.observer_lon}>"


class TargetType(db.Model):
    __tablename__ = "target_types"
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)  # emission, galaxy, etc.
    recommended_palette = db.Column(db.String(16), nullable=False)  # SHO, LRGB, etc.
    description = db.Column(db.Text)  # Why this palette works
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    object_mappings = relationship("ObjectMapping", back_populates="target_type", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<TargetType {self.name} -> {self.recommended_palette}>"


class ObjectMapping(db.Model):
    __tablename__ = "object_mappings"
    
    id = db.Column(db.Integer, primary_key=True)
    object_name = db.Column(db.String(128), unique=True, nullable=False)  # "NGC 6960", "M31", etc.
    target_type_id = db.Column(db.Integer, db.ForeignKey("target_types.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    target_type = relationship("TargetType", back_populates="object_mappings")
    
    def __repr__(self):
        return f"<ObjectMapping {self.object_name} -> {self.target_type.name if self.target_type else 'None'}>"


class ResolverCache(db.Model):
    """Persistent cache for astronomical name resolutions.

    Schema uses only generic SQLAlchemy types so that SQLite (dev) and
    PostgreSQL (prod) produce *identical* DDL — no dialect-specific
    drift allowed.

    Negative-hit caching: when every source in the chain misses, a row
    is written with ``negative=True`` so that repeated bad queries
    don't keep hitting the network. Negative entries expire faster than
    positive ones (see ``ttl_days``).
    """

    __tablename__ = "resolver_cache"

    id = db.Column(db.Integer, primary_key=True)
    # Casefolded + whitespace-collapsed input. Unique so each user-typed
    # name has at most one row.
    input_key = db.Column(db.String(256), unique=True, nullable=False, index=True)
    canonical_name = db.Column(db.String(128), nullable=True)
    ra_hours = db.Column(db.Float, nullable=True)
    dec_deg = db.Column(db.Float, nullable=True)
    object_type = db.Column(db.String(64), nullable=True)
    target_type = db.Column(db.String(32), nullable=True)
    # JSON-encoded list[str] of human-readable aliases. Stored as TEXT for
    # SQLite/PG portability.
    common_names_json = db.Column(db.Text, nullable=True)
    # JSON-encoded list[str] of cross-catalog designations (e.g.
    # ["NGC 6992", "Caldwell 33"]). Kept separate from common_names so
    # the UI can distinguish nicknames from alternate catalog IDs.
    catalog_aliases_json = db.Column(db.Text, nullable=True)
    magnitude = db.Column(db.Float, nullable=True)
    source = db.Column(db.String(32), nullable=True)
    negative = db.Column(db.Boolean, nullable=False, default=False)
    resolved_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ttl_days = db.Column(db.Integer, nullable=False, default=90)

    def __repr__(self):
        kind = "NEG" if self.negative else "POS"
        return f"<ResolverCache {kind} {self.input_key!r} -> {self.canonical_name!r}>"


class Palette(db.Model):
    __tablename__ = "palettes"
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)  # "SHO", "HOO", "LRGB", "Custom Foraxx"
    display_name = db.Column(db.String(128), nullable=False)  # "Sulfur-Hydrogen-Oxygen (SHO)"
    description = db.Column(db.Text)  # Detailed description
    filters_json = db.Column(db.Text, nullable=False)  # JSON with filter definitions
    is_system = db.Column(db.Boolean, default=False)  # True for built-in palettes, False for user custom
    is_active = db.Column(db.Boolean, default=True)  # Can be disabled without deletion
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    targets = relationship("Target", back_populates="palette")
    target_plans = relationship("TargetPlan", back_populates="palette")
    
    def __repr__(self):
        return f"<Palette {self.name} ({'system' if self.is_system else 'custom'})>"
    
    def get_filters(self):
        """Get filter configuration as Python dict."""
        import json
        return json.loads(self.filters_json) if self.filters_json else {}
    
    def set_filters(self, filters_dict):
        """Set filter configuration from Python dict."""
        import json
        self.filters_json = json.dumps(filters_dict)


# ---------------------------------------------------------------------------
# FILTER & FILTER WHEEL MODELS
# ---------------------------------------------------------------------------

class Filter(db.Model):
    """Abstract filter type (app-wide definition)."""
    __tablename__ = "filters"
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(16), unique=True, nullable=False)  # Code: "H", "O", "S", "L", etc.
    display_name = db.Column(db.String(128), nullable=False)  # "Hydrogen Alpha", "Oxygen III"
    filter_type = db.Column(db.String(32), default="narrowband")  # narrowband, broadband, other
    default_exposure = db.Column(db.Integer, default=300)  # Default sub exposure in seconds
    astrobin_id = db.Column(db.Integer, nullable=True)  # AstroBin equipment database ID for CSV export
    is_system = db.Column(db.Boolean, default=False)  # True for built-in filters
    is_active = db.Column(db.Boolean, default=True)  # Can be deactivated (not deleted) for system
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    wheel_slots = relationship("FilterWheelSlot", back_populates="filter", cascade="all, delete-orphan")
    palette_filters = relationship("PaletteFilter", back_populates="filter", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Filter {self.name} ({self.display_name})>"


class FilterWheel(db.Model):
    """Physical filter wheel hardware profile."""
    __tablename__ = "filter_wheels"
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)  # "ZWO 8x1.25"", "Astronomik 7x2""
    slot_count = db.Column(db.Integer, nullable=False, default=8)  # Number of filter positions
    filter_size = db.Column(db.String(16), default="1.25\"")  # "1.25"", "2"", "36mm"
    nina_profile_name = db.Column(db.String(128))  # Optional NINA equipment profile name
    is_active = db.Column(db.Boolean, default=False)  # Only one wheel active at a time
    is_default = db.Column(db.Boolean, default=False)  # Mark as default wheel
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    slots = relationship("FilterWheelSlot", back_populates="wheel", cascade="all, delete-orphan",
                        order_by="FilterWheelSlot.position")
    
    def __repr__(self):
        return f"<FilterWheel {self.name} ({self.slot_count} slots)>"
    
    def get_filter_at_position(self, position):
        """Get the filter at a specific wheel position."""
        for slot in self.slots:
            if slot.position == position:
                return slot.filter
        return None
    
    def get_slot_by_filter_name(self, filter_name):
        """Get slot info by filter name/code."""
        for slot in self.slots:
            if slot.filter and slot.filter.name == filter_name:
                return slot
        return None


class FilterWheelSlot(db.Model):
    """Position mapping linking filters to physical wheel slots."""
    __tablename__ = "filter_wheel_slots"
    
    id = db.Column(db.Integer, primary_key=True)
    filter_wheel_id = db.Column(db.Integer, db.ForeignKey("filter_wheels.id"), nullable=False)
    filter_id = db.Column(db.Integer, db.ForeignKey("filters.id"), nullable=True)  # NULL = empty slot
    position = db.Column(db.Integer, nullable=False)  # 0-indexed wheel position
    nina_filter_name = db.Column(db.String(64))  # NINA-specific name: "Ha", "OIII", "SII"
    physical_filter_brand = db.Column(db.String(128))  # Optional: "Antlia", "Optolong", "Astronomik"
    notes = db.Column(db.Text)  # Optional notes about this slot
    
    # Relationships
    wheel = relationship("FilterWheel", back_populates="slots")
    filter = relationship("Filter", back_populates="wheel_slots")
    
    # Unique constraint: one filter per position per wheel
    __table_args__ = (
        db.UniqueConstraint('filter_wheel_id', 'position', name='unique_wheel_position'),
    )
    
    def __repr__(self):
        filter_name = self.filter.name if self.filter else "Empty"
        return f"<FilterWheelSlot pos={self.position} filter={filter_name}>"


class PaletteFilter(db.Model):
    """Association table linking Palettes to Filters with additional attributes."""
    __tablename__ = "palette_filters"
    
    id = db.Column(db.Integer, primary_key=True)
    palette_id = db.Column(db.Integer, db.ForeignKey("palettes.id"), nullable=False)
    filter_id = db.Column(db.Integer, db.ForeignKey("filters.id"), nullable=False)
    rgb_channel = db.Column(db.String(16))  # "red", "green", "blue", "luminance", or combo like "GB"
    weight = db.Column(db.Float, default=1.0)  # Relative weight for this filter in the palette
    order = db.Column(db.Integer, default=0)  # Display/processing order
    
    # Relationships
    palette = relationship("Palette", backref="palette_filters_rel")
    filter = relationship("Filter", back_populates="palette_filters")
    
    # Unique constraint: one filter per palette
    __table_args__ = (
        db.UniqueConstraint('palette_id', 'filter_id', name='unique_palette_filter'),
    )
    
    def __repr__(self):
        return f"<PaletteFilter palette={self.palette_id} filter={self.filter_id} rgb={self.rgb_channel}>"


class Target(db.Model):
    __tablename__ = "targets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    catalog_id = db.Column(db.String(64))
    target_type = db.Column(db.String(64))  # Keep for backward compatibility
    target_type_id = db.Column(db.Integer, db.ForeignKey("target_types.id"))  # New FK reference

    # RA in decimal hours, Dec in decimal degrees
    ra_hours = db.Column(db.Float, nullable=False)
    dec_deg = db.Column(db.Float, nullable=False)

    notes = db.Column(db.Text)
    pixinsight_workflow = db.Column(db.Text)

    preferred_palette = db.Column(db.String(64), default="SHO")  # Keep for backward compatibility
    palette_id = db.Column(db.Integer, db.ForeignKey("palettes.id"))  # New FK reference
    packup_time_local = db.Column(db.String(5), default="01:00")  # "HH:MM"
    
    # Configuration overrides (NULL = use global config)
    override_packup_time = db.Column(db.String(5))  # NULL = use global default
    override_min_altitude = db.Column(db.Float)     # NULL = use global default

    # Calibration tracking (opt-in per target)
    calibration_tracking_enabled = db.Column(db.Boolean, default=False)
    override_calibration_darks = db.Column(db.Integer)
    override_calibration_flats_per_channel = db.Column(db.Integer)
    override_calibration_dark_flats_per_channel = db.Column(db.Integer)
    override_calibration_bias = db.Column(db.Integer)
    override_calibration_two_point = db.Column(db.Boolean)

    final_image_filename = db.Column(db.String(255))

    # NEW: when this target (i.e. this "project") was created
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Archive/completion status
    is_archived = db.Column(db.Boolean, default=False)
    archived_at = db.Column(db.DateTime)
    completion_notes = db.Column(db.Text)  # Notes about the completed project

    plans = relationship("TargetPlan", back_populates="target",
                         cascade="all, delete-orphan")
    sessions = relationship("ImagingSession", back_populates="target",
                            cascade="all, delete-orphan")
    calibration_captures = relationship(
        "CalibrationCapture", back_populates="target", cascade="all, delete-orphan"
    )
    calibration_checkpoint_skips = relationship(
        "CalibrationCheckpointSkip", back_populates="target", cascade="all, delete-orphan"
    )
    palette = relationship("Palette", back_populates="targets")


class TargetPlan(db.Model):
    __tablename__ = "target_plans"

    id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.Integer, db.ForeignKey("targets.id"), nullable=False)
    palette_name = db.Column(db.String(64), nullable=False)  # Keep for backward compatibility
    palette_id = db.Column(db.Integer, db.ForeignKey("palettes.id"))  # New FK reference

    # JSON string:
    # {
    #   "channels": [
    #       {"name": "H", "label": "Ha", "weight": 0.5,
    #        "weight_fraction": 0.5, "planned_minutes": 180},
    #       ...
    #   ],
    #   "dominant_channel": "H",
    #   "total_planned_minutes": 360,
    #   "palette": "SHO"
    # }
    plan_json = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    target = relationship("Target", back_populates="plans")
    palette = relationship("Palette", back_populates="target_plans")


class ImagingSession(db.Model):
    __tablename__ = "imaging_sessions"

    id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.Integer, db.ForeignKey("targets.id"), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.now().date)
    channel = db.Column(db.String(16), nullable=False)  # H, O, S, L, R, G, B
    sub_exposure_seconds = db.Column(db.Integer, nullable=False)
    sub_count = db.Column(db.Integer, nullable=False)

    notes = db.Column(db.Text)

    target = relationship("Target", back_populates="sessions")


class CalibrationCapture(db.Model):
    __tablename__ = "calibration_captures"

    id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.Integer, db.ForeignKey("targets.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.now().date)
    frame_type = db.Column(db.String(16), nullable=False)  # dark, flat, dark_flat, bias
    channel = db.Column(db.String(16))  # required for flat/dark_flat
    sub_exposure_seconds = db.Column(db.Float)  # required for dark — matches plan light sub-exp
    checkpoint = db.Column(db.String(16))  # midpoint, end, manual
    frame_count = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text)

    target = relationship("Target", back_populates="calibration_captures")


class CalibrationCheckpointSkip(db.Model):
    __tablename__ = "calibration_checkpoint_skips"

    id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.Integer, db.ForeignKey("targets.id"), nullable=False)
    channel = db.Column(db.String(16), nullable=False)
    frame_type = db.Column(db.String(16), nullable=False)  # flat, dark_flat
    checkpoint = db.Column(db.String(16), nullable=False)  # midpoint, end
    skipped_at = db.Column(db.DateTime, default=datetime.utcnow)

    target = relationship("Target", back_populates="calibration_checkpoint_skips")

    __table_args__ = (
        db.UniqueConstraint(
            "target_id", "channel", "frame_type", "checkpoint",
            name="unique_calibration_checkpoint_skip",
        ),
    )


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def get_local_tz_iana():
    tz_name = os.environ.get("OBSERVER_TZ", "Asia/Riyadh")
    try:
        return ZoneInfo(tz_name)
    except:
        return ZoneInfo("Asia/Riyadh")


def get_local_tz():
    """
    Return a tzinfo for local time.

    - If OBSERVER_TZ looks like a KSA-ish timezone, use fixed UTC+3.
    - Otherwise, try zoneinfo if available.
    - Fallback to UTC if nothing else works.
    """
    tz_name = os.environ.get("OBSERVER_TZ", "Asia/Riyadh")

    # Treat these as "KSA time", fixed UTC+3
    if tz_name in ("Asia/Riyadh", "KSA", "UTC+3", "+03:00"):
        return timezone(timedelta(hours=3))

    # Best effort: try zoneinfo if installed
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        # Last resort: UTC
        return timezone.utc


def parse_time_str(tstr, default="01:00") -> time:
    """Parse 'HH:MM' into a time object; fall back if invalid."""
    try:
        h, m = map(int, tstr.split(":"))
        return time(hour=h, minute=m)
    except Exception:
        dh, dm = map(int, default.split(":"))
        return time(hour=dh, minute=dm)


def get_global_config():
    """Get global configuration, creating default if none exists."""
    config = GlobalConfig.query.first()
    if not config:
        config = GlobalConfig()
        db.session.add(config)
        db.session.commit()
    return config


def get_effective_packup_time(target):
    """Get effective pack-up time for target (override from settings, or target's own time)."""
    # First priority: explicit override from target settings page
    if target.override_packup_time:
        return target.override_packup_time
    
    # Second priority: target's own pack-up time (always has a value)
    if target.packup_time_local:
        return target.packup_time_local
    
    # Fallback: global default (should rarely be needed since packup_time_local should always be set)
    return get_global_config().default_packup_time


def get_effective_min_altitude(target):
    """Get effective minimum altitude for target (override or global default)."""
    if target.override_min_altitude is not None:
        return target.override_min_altitude
    return get_global_config().default_min_altitude


def get_effective_calibration_config(target):
    """Resolved calibration settings for a target (global defaults + overrides).

    Note: ``default_calibration_two_point`` / ``override_calibration_two_point``
    columns are retained this release but no longer read — the two-point flat
    nudge was dropped in v2.5.0. Columns will be removed in v2.6 (see roadmap).
    """
    global_config = get_global_config()
    return {
        "enabled": bool(target.calibration_tracking_enabled),
        "darks": (
            target.override_calibration_darks
            if target.override_calibration_darks is not None
            else global_config.default_calibration_darks
        ),
        "flats_per_channel": (
            target.override_calibration_flats_per_channel
            if target.override_calibration_flats_per_channel is not None
            else global_config.default_calibration_flats_per_channel
        ),
        "dark_flats_per_channel": (
            target.override_calibration_dark_flats_per_channel
            if target.override_calibration_dark_flats_per_channel is not None
            else global_config.default_calibration_dark_flats_per_channel
        ),
        "bias": (
            target.override_calibration_bias
            if target.override_calibration_bias is not None
            else global_config.default_calibration_bias
        ),
    }


def get_target_plan_form_context(target):
    """Channels and sub-exposure options from the target's latest plan."""
    plan = (
        TargetPlan.query.filter_by(target_id=target.id)
        .order_by(TargetPlan.created_at.desc())
        .first()
    )
    if not plan:
        return [], [], None
    plan_data = json.loads(plan.plan_json)
    channels = [c.get("name") for c in plan_data.get("channels", []) if c.get("name")]
    from calibration_utils import plan_unique_sub_exposures

    sub_exposures = plan_unique_sub_exposures(plan_data)
    return channels, sub_exposures, plan_data


def get_observer_location():
    """Get observer location from global config."""
    config = get_global_config()
    return config.observer_lat, config.observer_lon, config.observer_elev_m


def get_recommended_palette(target_type):
    """Get recommended palette based on target type."""
    # Try to get from TargetType table first
    target_type_obj = TargetType.query.filter_by(name=target_type).first()
    if target_type_obj:
        return target_type_obj.recommended_palette
    
    # Fallback to hardcoded mapping
    palette_map = {
        "emission": "SHO",
        "diffuse": "HOO", 
        "reflection": "LRGB",
        "galaxy": "LRGB",
        "cluster": "LRGB",
        "planetary": "SHO",
        "supernova_remnant": "SHO",
        "other": "SHO"
    }
    return palette_map.get(target_type, "SHO")


def detect_target_type(catalog_name):
    """Detect target type using ObjectMapping database."""
    if not catalog_name:
        return "other"
    
    # Clean up the catalog name for matching
    clean_name = catalog_name.strip().upper()
    
    # Check ObjectMapping table first
    mapping = ObjectMapping.query.filter(
        db.func.upper(ObjectMapping.object_name) == clean_name
    ).first()
    
    if mapping and mapping.target_type:
        return mapping.target_type.name
    
    # Fallback to old hardcoded logic for backward compatibility
    return detect_target_type_fallback(catalog_name)


def detect_target_type_fallback(catalog_name):
    """Fallback detection using hardcoded patterns (legacy)."""
    name_lower = catalog_name.lower().strip()
    
    # Keep existing hardcoded logic as fallback
    if any(x in name_lower for x in ['ngc 6960', 'ngc 6992', 'ngc 6979', 'ngc 6974']):
        return "supernova_remnant"
    elif any(x in name_lower for x in ['ic 1805', 'ic 1848', 'ngc 7635', 'ic 1396']):
        return "emission"
    elif any(x in name_lower for x in ['ngc 7023', 'ic 2118', 'ngc 1977']):
        return "reflection"
    elif any(x in name_lower for x in ['m31', 'm33', 'm81', 'm82', 'm101', 'ngc 891', 'ngc 4565']):
        return "galaxy"
    elif any(x in name_lower for x in ['m45', 'm44', 'ngc 869', 'ngc 884']):
        return "cluster"
    elif any(x in name_lower for x in ['ngc 7293', 'ngc 6720', 'ngc 6853', 'ngc 3132']):
        return "planetary"
    elif any(x in name_lower for x in ['sh2-', 'sh 2-', 'sharpless']):
        return "emission"
    
    return "other"


def add_object_mapping(catalog_name, target_type_name):
    """Add a new object mapping to the database."""
    if not catalog_name or not target_type_name:
        return False
    
    # Check if mapping already exists
    clean_name = catalog_name.strip().upper()
    existing = ObjectMapping.query.filter(
        db.func.upper(ObjectMapping.object_name) == clean_name
    ).first()
    
    if existing:
        return False  # Already exists
    
    # Find target type
    target_type_obj = TargetType.query.filter_by(name=target_type_name).first()
    if not target_type_obj:
        return False  # Invalid target type
    
    # Create new mapping
    mapping = ObjectMapping(
        object_name=catalog_name.strip(),
        target_type_id=target_type_obj.id
    )
    
    try:
        db.session.add(mapping)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        return False


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    from collections import defaultdict

    # Separate active and archived targets
    active_targets = Target.query.filter(
        (Target.is_archived == False) | (Target.is_archived == None)
    ).order_by(Target.name).all()
    
    archived_targets = Target.query.filter(Target.is_archived == True).order_by(Target.archived_at.desc()).all()

    # Observer location from global config
    lat, lon, elev = get_observer_location()

    summaries = []

    for t in active_targets:
        # Latest plan for current preferred palette
        plan = (
            TargetPlan.query
            .filter_by(target_id=t.id, palette_name=t.preferred_palette)
            .order_by(TargetPlan.created_at.desc())
            .first()
        )

        if plan:
            plan_data = json.loads(plan.plan_json)
            planned_total = float(plan_data.get("total_planned_minutes", 0) or 0)
            channels = plan_data.get("channels", [])
        else:
            plan_data = None
            planned_total = 0.0
            channels = []

        # Progress: accumulate per-channel & total
        total_seconds = 0.0
        per_channel_seconds = defaultdict(float)

        for s in t.sessions:
            secs = s.sub_exposure_seconds * s.sub_count
            total_seconds += secs
            per_channel_seconds[s.channel] += secs

        done_minutes = total_seconds / 60.0
        remaining_minutes = max(planned_total - done_minutes, 0.0)

        # Suggested channel = one with largest remaining seconds
        suggested_channel = None
        suggested_label = None
        max_remaining_ch_sec = -1.0

        for ch in channels:
            name = ch.get("name")
            label = ch.get("label", name)
            ch_planned_min = float(ch.get("planned_minutes", 0) or 0)
            planned_sec = ch_planned_min * 60.0
            done_sec = per_channel_seconds.get(name, 0.0)
            rem_sec = max(planned_sec - done_sec, 0.0)
            if rem_sec > max_remaining_ch_sec:
                max_remaining_ch_sec = rem_sec
                suggested_channel = name
                suggested_label = label

        # Tonight's window for this target
        packup_time = parse_time_str(get_effective_packup_time(t))
        window_info = compute_target_window(
            ra_hours=t.ra_hours,
            dec_deg=t.dec_deg,
            latitude_deg=lat,
            longitude_deg=lon,
            elevation_m=elev,
            packup_time_local=packup_time,
            min_altitude_deg=get_effective_min_altitude(t),
        )

        if window_info.get("deps_available"):
            window_minutes = float(window_info.get("total_minutes") or 0.0)
        else:
            window_minutes = 0.0

        # Best you can realistically do tonight for this target
        best_tonight_minutes = min(window_minutes, remaining_minutes) if remaining_minutes > 0 else 0.0

        # Basic ratios (we'll normalize later too)
        if planned_total > 0:
            completion_ratio = done_minutes / planned_total
            remaining_ratio = remaining_minutes / planned_total
        else:
            completion_ratio = 0.0
            remaining_ratio = 0.0

        # Window fit: how much of remaining can tonight cover (capped at 1.0)
        if remaining_minutes > 0:
            window_fit_ratio = min(1.0, window_minutes / remaining_minutes)
            tonight_completion_fraction = best_tonight_minutes / remaining_minutes
        else:
            window_fit_ratio = 0.0
            tonight_completion_fraction = 0.0

        created_local = (t.created_at.replace(tzinfo=timezone.utc).astimezone(get_local_tz()) if t.created_at else None)

        summaries.append({
            "target": t,
            "plan_data": plan_data,
            "planned_total": round(planned_total, 1),
            "done_total": round(done_minutes, 1),
            "remaining_total": round(remaining_minutes, 1),
            "window_minutes": round(window_minutes, 1),
            "best_tonight_minutes": round(best_tonight_minutes, 1),
            "suggested_channel": suggested_channel,
            "suggested_channel_label": suggested_label,
            "completion_ratio_raw": completion_ratio,
            "remaining_ratio_raw": remaining_ratio,
            "window_fit_ratio_raw": window_fit_ratio,
            "tonight_completion_fraction_raw": tonight_completion_fraction,
            "created_local": created_local,
        })

    # Second pass: normalize across all targets & compute a priority score
    # Only consider targets that have a plan and some remaining time.
    active = [s for s in summaries if s["planned_total"] > 0 and s["remaining_total"] > 0]

    if active:
        max_remaining = max(s["remaining_total"] for s in active) or 1.0

        for s in active:
            remaining_total = s["remaining_total"]

            # 1 - remaining/ max_remaining  ->  high if this target has less remaining than others
            remaining_rel = 1.0 - (remaining_total / max_remaining)

            completion_ratio = s["completion_ratio_raw"]
            window_fit_ratio = s["window_fit_ratio_raw"]
            tonight_completion_fraction = s["tonight_completion_fraction_raw"]

            # Priority score (0–1-ish): favor almost-finished & finishable tonight
            priority_score = (
                0.35 * completion_ratio +
                0.25 * window_fit_ratio +
                0.20 * remaining_rel +
                0.20 * tonight_completion_fraction
            )

            s["priority_score"] = round(priority_score, 3)
            s["completion_pct"] = round(completion_ratio * 100, 1)
        # Non-active targets: set score to 0
        for s in summaries:
            if s not in active:
                s["priority_score"] = 0.0
                s["completion_pct"] = 0.0
    else:
        for s in summaries:
            s["priority_score"] = 0.0
            s["completion_pct"] = 0.0

    # Tonight's pick = highest priority_score among active
    tonight_pick = None
    if active:
        tonight_pick = max(active, key=lambda s: s["priority_score"])

    # Build archived summaries with basic info
    archived_summaries = []
    for t in archived_targets:
        plan = (
            TargetPlan.query
            .filter_by(target_id=t.id, palette_name=t.preferred_palette)
            .order_by(TargetPlan.created_at.desc())
            .first()
        )
        
        if plan:
            plan_data = json.loads(plan.plan_json)
            planned_total = float(plan_data.get("total_planned_minutes", 0) or 0)
        else:
            plan_data = None
            planned_total = 0.0
        
        # Calculate total done time
        total_seconds = sum(s.sub_exposure_seconds * s.sub_count for s in t.sessions)
        done_minutes = total_seconds / 60.0
        
        archived_at_local = (t.archived_at.replace(tzinfo=timezone.utc).astimezone(get_local_tz()) if t.archived_at else None)
        created_local = (t.created_at.replace(tzinfo=timezone.utc).astimezone(get_local_tz()) if t.created_at else None)
        
        archived_summaries.append({
            "target": t,
            "plan_data": plan_data,
            "planned_total": round(planned_total, 1),
            "done_total": round(done_minutes, 1),
            "archived_at_local": archived_at_local,
            "created_local": created_local,
        })

    return render_template(
        "index.html",
        target_summaries=summaries,
        archived_summaries=archived_summaries,
        tonight_pick=tonight_pick,
    )


@app.route("/target/new", methods=["GET", "POST"])
def new_target():
    if request.method == "POST":
        name = request.form.get("name")
        catalog_id = request.form.get("catalog_id") or None
        target_type = request.form.get("target_type") or None
        ra_hours = float(request.form.get("ra_hours"))
        dec_deg = float(request.form.get("dec_deg"))
        
        # Use submitted palette or get recommendation based on target type
        preferred_palette = request.form.get("preferred_palette")
        if not preferred_palette or preferred_palette == "auto":
            preferred_palette = get_recommended_palette(target_type)
        
        # Handle pack-up time: use submitted value, falling back to global default
        global_config = get_global_config()
        packup_time_local = request.form.get("packup_time_local") or global_config.default_packup_time

        target = Target(
            name=name,
            catalog_id=catalog_id,
            target_type=target_type,
            ra_hours=ra_hours,
            dec_deg=dec_deg,
            preferred_palette=preferred_palette,
            packup_time_local=packup_time_local,
        )
        db.session.add(target)
        db.session.commit()
        
        # Create object mapping for future auto-detection
        if catalog_id and target_type and target_type != "other":
            add_object_mapping(catalog_id, target_type)

        # Initial plan guess
        plan_json = build_default_plan_json(
            target_type=target_type,
            palette=preferred_palette,
            bortle=9,
        )
        plan = TargetPlan(
            target_id=target.id,
            palette_name=preferred_palette,
            plan_json=plan_json,
        )
        db.session.add(plan)
        db.session.commit()

        flash("Target created.", "success")
        return redirect(url_for("target_detail", target_id=target.id))

    # Pass global config to template for default values
    global_config = get_global_config()
    palettes = Palette.query.filter_by(is_active=True).order_by(Palette.name).all()
    return render_template("target_form.html", target=None, global_config=global_config, palettes=palettes)


@app.route("/target/<int:target_id>")
def target_detail(target_id):
    target = Target.query.get_or_404(target_id)

    # Latest plan for current preferred palette
    plan = (
        TargetPlan.query
        .filter_by(target_id=target.id, palette_name=target.preferred_palette)
        .order_by(TargetPlan.created_at.desc())
        .first()
    )
    plan_data = json.loads(plan.plan_json) if plan else None

    # Observer location and settings from config
    lat, lon, elev = get_observer_location()
    packup_time = parse_time_str(get_effective_packup_time(target))
    effective_min_alt = get_effective_min_altitude(target)

    window_info = compute_target_window(
        ra_hours=target.ra_hours,
        dec_deg=target.dec_deg,
        latitude_deg=lat,
        longitude_deg=lon,
        elevation_m=elev,
        packup_time_local=packup_time,
        min_altitude_deg=effective_min_alt,
    )

    # Progress: accumulate minutes and seconds per channel
    from collections import defaultdict
    progress_minutes = defaultdict(float)
    progress_seconds = defaultdict(float)

    for s in target.sessions:
        total_seconds = s.sub_exposure_seconds * s.sub_count
        progress_seconds[s.channel] += total_seconds
        progress_minutes[s.channel] += total_seconds / 60.0

    # Get active palettes for palette selector
    palettes = Palette.query.filter_by(is_active=True).order_by(Palette.name).all()

    # Get AstroBin ID map for export modal
    astrobin_filter_map = {f.name: f.astrobin_id for f in Filter.query.all() if f.astrobin_id}

    calibration_config = get_effective_calibration_config(target)
    calibration_data = None
    calibration_badges = {}
    calibration_export_totals = None
    calibration_api = None
    imaging_log_days = []
    if calibration_config["enabled"]:
        calibration_api = _build_calibration_api_response(target)
        calibration_data = {
            "summary": calibration_api["summary"],
            "suggestions": calibration_api["suggestions"],
        }
        calibration_badges = calibration_api["badges"]
    if target.calibration_captures:
        calibration_export_totals = aggregate_calibration_for_export(target.calibration_captures)
    astrobin_export_preview = None
    if target.sessions:
        export_filter_map = {}
        if plan_data:
            for ch in plan_data.get("channels", []):
                ch_name = ch.get("name", "")
                base_filter = (ch.get("nina_filter") or "").strip() or ch_name
                if ch_name:
                    export_filter_map[ch_name] = base_filter
        astrobin_export_preview = build_astrobin_export_rows(
            target.sessions,
            target.calibration_captures,
            export_filter_map,
            plan_data,
        )
    if target.sessions or target.calibration_captures:
        imaging_log_days = build_target_imaging_log_days(
            target.sessions, target.calibration_captures
        )

    return render_template(
        "target_detail.html",
        target=target,
        target_created_local=(
            target.created_at.replace(tzinfo=timezone.utc).astimezone(get_local_tz())
            if target.created_at
            else None
        ),
        plan=plan,
        plan_data=plan_data,
        window_info=window_info,
        progress_minutes=progress_minutes,
        progress_seconds=progress_seconds,
        palettes=palettes,
        astrobin_filter_map=astrobin_filter_map,
        calibration_config=calibration_config,
        calibration_data=calibration_data,
        calibration_api=calibration_api,
        calibration_badges=calibration_badges,
        calibration_export_totals=calibration_export_totals,
        astrobin_export_preview=astrobin_export_preview,
        imaging_log_days=imaging_log_days,
    )

@app.post("/target/<int:target_id>/export_nina")
def export_nina_sequence(target_id):
    target = Target.query.get_or_404(target_id)

    # --- REUSE SAME PLAN LOGIC AS target_detail ---
    plan = (
        TargetPlan.query
        .filter_by(target_id=target.id, palette_name=target.preferred_palette)
        .order_by(TargetPlan.created_at.desc())
        .first()
    )

    if not plan:
        flash("No plan defined for this target.", "warning")
        return redirect(url_for("target_detail", target_id=target.id))

    plan_data = json.loads(plan.plan_json) if plan else None
    if not plan_data or "channels" not in plan_data:
        flash("Plan JSON is missing channels.", "warning")
        return redirect(url_for("target_detail", target_id=target.id))

    # --- REUSE SAME PROGRESS LOGIC AS target_detail ---
    from collections import defaultdict
    progress_minutes = defaultdict(float)
    progress_seconds = defaultdict(float)

    for s in target.sessions:
        total_seconds = s.sub_exposure_seconds * s.sub_count
        progress_seconds[s.channel] += total_seconds
        progress_minutes[s.channel] += total_seconds / 60.0

    # --- BUILD BLOCKS FROM REMAINING SUBS ---
    blocks = []

    for ch in plan_data["channels"]:
        # ch is a dict: {"name": "H", "label": "...", "planned_minutes": 180, "sub_exposure_seconds": 300, ...}
        ch_name = ch.get("name")
        if not ch_name:
            continue

        # For NINA export, use nina_filter if available (for custom filters), otherwise use the channel name
        nina_channel = ch.get("nina_filter", ch_name)

        planned_minutes = ch.get("planned_minutes", 0) or 0
        sub_exp = ch.get("sub_exposure_seconds", 300) or 300

        done_sec = progress_seconds[ch_name]  # Still use original channel name for progress tracking
        planned_sec = planned_minutes * 60
        remaining_sec = max(planned_sec - done_sec, 0)

        if remaining_sec <= 0:
            continue

        frames = int(round(remaining_sec / sub_exp))
        if frames <= 0:
            continue

        blocks.append({
            "channel": nina_channel,      # Use mapped filter for NINA (e.g., "O" instead of "O_HDR_1")
            "exposure_s": sub_exp,        # e.g. 300
            "frames": frames,             # remaining frames
        })

    if not blocks:
        flash("No remaining subs to export for this target.", "info")
        return redirect(url_for("target_detail", target_id=target.id))

    # --- LOAD TEMPLATE & BUILD NINA SEQUENCE JSON ---
    template = load_nina_template("nina_template.json")
    seq_json = build_nina_sequence_from_blocks(
        template=template,
        target_name=target.name,
        camera_cool_temp=-10.0,
        blocks=blocks,
    )

    # --- RETURN AS DOWNLOAD ---
    filename = f"ArmillaryLab_{target.name.replace(' ', '_')}.json"
    buf = io.BytesIO(json.dumps(seq_json, indent=2).encode("utf-8"))

    return send_file(
        buf,
        mimetype="application/json",
        as_attachment=True,
        download_name=filename,
    )


@app.post("/target/<int:target_id>/export_astrobin")
def export_astrobin_csv(target_id):
    """Export imaging sessions for a target as AstroBin-compatible CSV."""
    target = Target.query.get_or_404(target_id)
    
    if not target.sessions:
        flash("No imaging sessions to export for this target.", "warning")
        return redirect(url_for("target_detail", target_id=target.id))
    
    # Get filter name mapping from the target's plan
    filter_name_map = {}  # Maps channel name (e.g., "O_HDR_1") to base filter (e.g., "O")
    plan = (
        TargetPlan.query
        .filter_by(target_id=target.id, palette_name=target.preferred_palette)
        .order_by(TargetPlan.created_at.desc())
        .first()
    )
    if plan:
        try:
            plan_data = json.loads(plan.plan_json)
            for ch in plan_data.get("channels", []):
                ch_name = ch.get("name", "")
                # Use nina_filter if available (for custom filters), otherwise use the channel name itself
                base_filter = (ch.get("nina_filter") or "").strip() or ch_name
                if ch_name:
                    filter_name_map[ch_name] = base_filter
        except (json.JSONDecodeError, KeyError):
            pass
    
    # Build AstroBin ID map from database filters
    astrobin_id_map = {}  # Maps filter name (e.g., "H") to AstroBin ID (e.g., 1955)
    for f in Filter.query.all():
        if f.astrobin_id:
            astrobin_id_map[f.name] = f.astrobin_id
    
    # Get form data with defaults
    binning = request.form.get("binning", "1")
    gain = request.form.get("gain", "100")
    sensor_cooling = request.form.get("sensor_cooling", "-10")
    bortle = request.form.get("bortle", "")
    use_tracked = request.form.get("use_tracked_calibration") == "on"
    plan_data = None
    if plan:
        try:
            plan_data = json.loads(plan.plan_json)
        except json.JSONDecodeError:
            pass

    include_darks = include_flats = include_flat_darks = include_bias = False
    uniform_cal = {"darks": "", "flats": "", "flat_darks": "", "bias": ""}

    if use_tracked and target.calibration_captures:
        export_rows = build_astrobin_export_rows(
            target.sessions,
            target.calibration_captures,
            filter_name_map,
            plan_data,
        )
        include_darks = any(r["darks"] for r in export_rows)
        include_flats = any(r["flats"] for r in export_rows)
        include_flat_darks = any(r["flat_darks"] for r in export_rows)
        include_bias = any(r["bias"] for r in export_rows)
    else:
        cal_cols = resolve_astrobin_calibration_columns(
            {
                "darks": request.form.get("darks", ""),
                "flats": request.form.get("flats", ""),
                "flat_darks": request.form.get("flat_darks", ""),
                "bias": request.form.get("bias", ""),
            },
            target.calibration_captures,
            use_tracked=use_tracked,
        )
        uniform_cal = cal_cols
        include_darks = bool(cal_cols["darks"])
        include_flats = bool(cal_cols["flats"])
        include_flat_darks = bool(cal_cols["flat_darks"])
        include_bias = bool(cal_cols["bias"])
        from collections import defaultdict
        sessions_grouped = defaultdict(lambda: {"number": 0, "duration": None})
        for session in target.sessions:
            base_filter = filter_name_map.get(session.channel, session.channel)
            key = (session.date.strftime("%Y-%m-%d"), base_filter, session.sub_exposure_seconds)
            sessions_grouped[key]["number"] += session.sub_count
            sessions_grouped[key]["duration"] = session.sub_exposure_seconds
        export_rows = []
        for (date, filter_name, duration), data in sorted(sessions_grouped.items()):
            export_rows.append({
                "date": date,
                "filter_name": filter_name,
                "number": data["number"],
                "duration": duration,
                "darks": int(uniform_cal["darks"]) if uniform_cal["darks"] else 0,
                "flats": int(uniform_cal["flats"]) if uniform_cal["flats"] else 0,
                "flat_darks": int(uniform_cal["flat_darks"]) if uniform_cal["flat_darks"] else 0,
                "bias": int(uniform_cal["bias"]) if uniform_cal["bias"] else 0,
            })
    
    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    header = ["date", "filter", "number", "duration", "binning", "gain", "sensorCooling"]
    if include_darks:
        header.append("darks")
    if include_flats:
        header.append("flats")
    if include_flat_darks:
        header.append("flatDarks")
    if include_bias:
        header.append("bias")
    if bortle:
        header.append("bortle")
    writer.writerow(header)
    
    # Track filters missing AstroBin IDs
    filters_missing_ids = []
    
    # Write rows
    for row_data in export_rows:
        filter_name = row_data["filter_name"]
        filter_value = astrobin_id_map.get(filter_name, filter_name)
        if filter_name not in astrobin_id_map and filter_name not in filters_missing_ids:
            filters_missing_ids.append(filter_name)
        
        row = [
            row_data["date"],
            filter_value,
            row_data["number"],
            row_data["duration"],
            binning,
            gain,
            sensor_cooling,
        ]
        if include_darks:
            row.append(row_data["darks"] or "")
        if include_flats:
            row.append(row_data["flats"] or "")
        if include_flat_darks:
            row.append(row_data["flat_darks"] or "")
        if include_bias:
            row.append(row_data["bias"] or "")
        if bortle:
            row.append(bortle)
        writer.writerow(row)
    
    # Flash warning if some filters are missing AstroBin IDs
    if filters_missing_ids:
        flash(f"Warning: The following filters are missing AstroBin IDs and will need manual editing: {', '.join(filters_missing_ids)}. "
              f"Go to Filter Settings to add AstroBin IDs for proper import.", "warning")
    
    # Prepare file for download
    output.seek(0)
    buf = io.BytesIO(output.getvalue().encode("utf-8"))
    
    filename = f"AstroBin_{target.name.replace(' ', '_')}.csv"
    
    return send_file(
        buf,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/target/<int:target_id>/delete", methods=["POST"])
def delete_target(target_id):
    target = Target.query.get_or_404(target_id)

    # Delete final image file if present
    if target.final_image_filename:
        upload_folder = app.config.get("UPLOAD_FOLDER", "uploads")
        img_path = os.path.join(upload_folder, target.final_image_filename)
        try:
            if os.path.exists(img_path):
                os.remove(img_path)
        except OSError:
            # Not fatal if we can't remove the file
            pass

    # Delete imaging sessions
    for s in list(target.sessions):
        db.session.delete(s)

    # Delete plans
    plans = TargetPlan.query.filter_by(target_id=target.id).all()
    for p in plans:
        db.session.delete(p)

    # Delete target itself
    db.session.delete(target)
    db.session.commit()

    flash(f"Target '{target.name}' and all associated data were deleted.", "success")
    return redirect(url_for("index"))


@app.route("/target/<int:target_id>/archive", methods=["POST"])
def archive_target(target_id):
    """Mark a target as complete/archived."""
    target = Target.query.get_or_404(target_id)
    
    completion_notes = request.form.get("completion_notes", "")
    
    target.is_archived = True
    target.archived_at = datetime.utcnow()
    target.completion_notes = completion_notes
    
    db.session.commit()
    flash(f"Target '{target.name}' has been marked as complete and archived.", "success")
    return redirect(url_for("target_detail", target_id=target.id))


@app.route("/target/<int:target_id>/unarchive", methods=["POST"])
def unarchive_target(target_id):
    """Restore an archived target to active status."""
    target = Target.query.get_or_404(target_id)
    
    target.is_archived = False
    target.archived_at = None
    # Keep completion_notes for reference
    
    db.session.commit()
    flash(f"Target '{target.name}' has been restored to active status.", "success")
    return redirect(url_for("target_detail", target_id=target.id))


@app.route("/target/<int:target_id>/clone", methods=["POST"])
def clone_target(target_id):
    """Clone an archived target and reset its progress to start fresh."""
    original = Target.query.get_or_404(target_id)
    
    # Create new target with same details
    new_target = Target(
        name=f"{original.name} (Copy)",
        catalog_id=original.catalog_id,
        target_type=original.target_type,
        target_type_id=original.target_type_id,
        ra_hours=original.ra_hours,
        dec_deg=original.dec_deg,
        notes=original.notes,
        pixinsight_workflow=original.pixinsight_workflow,
        preferred_palette=original.preferred_palette,
        palette_id=original.palette_id,
        packup_time_local=original.packup_time_local,
        override_packup_time=original.override_packup_time,
        override_min_altitude=original.override_min_altitude,
        calibration_tracking_enabled=original.calibration_tracking_enabled,
        override_calibration_darks=original.override_calibration_darks,
        override_calibration_flats_per_channel=original.override_calibration_flats_per_channel,
        override_calibration_dark_flats_per_channel=original.override_calibration_dark_flats_per_channel,
        override_calibration_bias=original.override_calibration_bias,
        override_calibration_two_point=original.override_calibration_two_point,
        # Don't copy: final_image_filename, is_archived, archived_at, completion_notes
        # Don't copy: created_at (will be set to now automatically)
    )
    
    db.session.add(new_target)
    db.session.flush()  # Get the new target ID
    
    # Clone all plans but reset progress (no sessions copied)
    for plan in original.plans:
        plan_data = json.loads(plan.plan_json)
        new_plan = TargetPlan(
            target_id=new_target.id,
            palette_name=plan.palette_name,
            palette_id=plan.palette_id,
            plan_json=plan.plan_json,  # Copy the plan structure
        )
        db.session.add(new_plan)
    
    db.session.commit()
    
    flash(f"Target '{original.name}' has been cloned as '{new_target.name}' with all progress reset.", "success")
    return redirect(url_for("target_detail", target_id=new_target.id))


@app.route("/target/<int:target_id>/edit", methods=["GET", "POST"])
def edit_target(target_id):
    target = Target.query.get_or_404(target_id)

    if request.method == "POST":
        target.name = request.form.get("name")
        target.catalog_id = request.form.get("catalog_id") or None
        target.target_type = request.form.get("target_type") or None
        target.ra_hours = float(request.form.get("ra_hours"))
        target.dec_deg = float(request.form.get("dec_deg"))
        target.preferred_palette = request.form.get("preferred_palette") or target.preferred_palette
        target.packup_time_local = request.form.get("packup_time_local") or target.packup_time_local
        target.notes = request.form.get("notes")
        target.pixinsight_workflow = request.form.get("pixinsight_workflow")

        db.session.commit()
        flash("Target updated.", "success")
        return redirect(url_for("target_detail", target_id=target.id))

    # Pass global config to template for default values
    global_config = get_global_config()
    palettes = Palette.query.filter_by(is_active=True).order_by(Palette.name).all()
    return render_template("target_form.html", target=target, global_config=global_config, palettes=palettes)


@app.route("/target/<int:target_id>/update-notes", methods=["POST"])
def update_target_notes(target_id):
    target = Target.query.get_or_404(target_id)
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    target.notes = data.get("notes", "")
    db.session.commit()
    return jsonify({"ok": True, "notes": target.notes})


@app.route("/target/<int:target_id>/update-pixinsight-workflow", methods=["POST"])
def update_target_pixinsight_workflow(target_id):
    target = Target.query.get_or_404(target_id)
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    target.pixinsight_workflow = data.get("pixinsight_workflow", "")
    db.session.commit()
    return jsonify({"ok": True, "pixinsight_workflow": target.pixinsight_workflow})


@app.route("/target/<int:target_id>/plan/new", methods=["POST"])
def new_plan(target_id):
    target = Target.query.get_or_404(target_id)
    palette = request.form.get("palette") or target.preferred_palette

    target.preferred_palette = palette
    plan_json = build_default_plan_json(
        target_type=target.target_type,
        palette=palette,
        bortle=9,
    )
    plan = TargetPlan(
        target_id=target.id,
        palette_name=palette,
        plan_json=plan_json,
    )
    db.session.add(plan)
    db.session.commit()

    flash(f"New plan created for palette {palette}.", "success")
    return redirect(url_for("target_detail", target_id=target.id))


@app.route("/target/<int:target_id>/plan/update", methods=["POST"])
def update_plan(target_id):
    target = Target.query.get_or_404(target_id)

    # Get current plan for the preferred palette
    plan = (
        TargetPlan.query
        .filter_by(target_id=target.id, palette_name=target.preferred_palette)
        .order_by(TargetPlan.created_at.desc())
        .first()
    )
    if not plan:
        flash("No plan found to update.", "danger")
        return redirect(url_for("target_detail", target_id=target.id))

    data = json.loads(plan.plan_json)
    channels = data.get("channels", [])
    if not channels:
        flash("Plan JSON is missing channels.", "danger")
        return redirect(url_for("target_detail", target_id=target.id))

    # Handle filter removal
    removed_filters = request.form.getlist("removed_filter")
    if removed_filters:
        channels = [c for c in channels if c.get("name") not in removed_filters]

    # Handle custom filter addition
    custom_filters = {}
    for key in request.form.keys():
        if key.startswith("custom_") and key.endswith("_name"):
            # Extract the custom filter ID
            parts = key.split("_")
            if len(parts) >= 3:
                custom_id = parts[1]
                custom_filters[custom_id] = {}

    # Build custom filters
    for custom_id in custom_filters.keys():
        name = request.form.get(f"custom_{custom_id}_name", "").strip()
        label = request.form.get(f"custom_{custom_id}_label", "").strip()
        nina_filter = request.form.get(f"custom_{custom_id}_nina_filter", "").strip()
        minutes = request.form.get(f"custom_{custom_id}_minutes", "0")
        exposure = request.form.get(f"custom_{custom_id}_exposure", "300")
        frames = request.form.get(f"custom_{custom_id}_frames", "0")
        weight = request.form.get(f"custom_{custom_id}_weight", "1.0")

        if name:
            # Use name as label if label is empty
            if not label:
                label = name
                
            try:
                # Check if channel already exists
                existing_names = [c.get("name") for c in channels]
                if name not in existing_names:
                    # Calculate missing values if needed
                    final_minutes = float(minutes) if minutes else 0.0
                    final_exposure = float(exposure) if exposure else 300.0
                    final_frames = int(float(frames)) if frames else 0
                    
                    # If we have exposure and frames but no minutes, calculate it
                    if final_exposure > 0 and final_frames > 0 and final_minutes == 0:
                        final_minutes = (final_exposure * final_frames) / 60.0
                    # If we have minutes and frames but no exposure, calculate it
                    elif final_minutes > 0 and final_frames > 0 and final_exposure == 0:
                        final_exposure = round((final_minutes * 60) / final_frames, 3)
                    # If we have minutes and exposure but no frames, calculate it
                    elif final_minutes > 0 and final_exposure > 0 and final_frames == 0:
                        final_frames = round((final_minutes * 60) / final_exposure)
                    
                    channels.append({
                        "name": name,
                        "label": label,
                        "nina_filter": nina_filter,  # Add mapping for NINA export
                        "planned_minutes": final_minutes,
                        "sub_exposure_seconds": final_exposure,
                        "weight": float(weight) if weight else 1.0,
                        "weight_fraction": 0.0  # Will be recalculated below
                    })
            except ValueError:
                # Skip invalid custom filters
                pass

    # Ensure numeric planned_minutes and sub_exposure_seconds fields exist
    for c in channels:
        c["planned_minutes"] = float(c.get("planned_minutes", 0) or 0)
        if "sub_exposure_seconds" not in c or not c["sub_exposure_seconds"]:
            # Sensible default if missing, consistent with astro_utils
            n = c.get("name")
            if n in ("H", "O", "S"):
                c["sub_exposure_seconds"] = 300
            elif n == "L":
                c["sub_exposure_seconds"] = 180
            else:
                c["sub_exposure_seconds"] = 180

    baseline_total = sum(c["planned_minutes"] for c in channels)

    # Original total (metadata or sum after normalization)
    try:
        orig_total_meta = float(data.get("total_planned_minutes") or 0)
    except (TypeError, ValueError):
        orig_total_meta = 0.0
    if not orig_total_meta or orig_total_meta <= 0:
        orig_total_meta = baseline_total

    scale_denom = orig_total_meta if orig_total_meta > 0 else baseline_total
    if scale_denom <= 0:
        scale_denom = baseline_total if baseline_total > 0 else 1.0

    # User-specified total
    form_total_raw = request.form.get("total_planned_minutes")
    new_total = None
    if form_total_raw:
        try:
            new_total = float(form_total_raw)
        except ValueError:
            new_total = None

    # If the user changed the master total relative to the saved plan, rescale
    # the existing channel minutes proportionally as a baseline. This only
    # affects channels that are NOT explicitly overridden in the form below,
    # so manual per-channel edits always win.
    if new_total is not None and new_total > 0 and scale_denom > 0:
        delta = abs(new_total - scale_denom)
        if delta > 0.001:
            scale = new_total / scale_denom
            for c in channels:
                c["planned_minutes"] = c["planned_minutes"] * scale

    # Apply per-channel overrides from the form. These always take precedence
    # over the proportional rescale so users can customize individual channel
    # times even when changing the master total in the same submit.
    for c in channels:
        name = c.get("name")
        # Per-channel minutes override
        field_name = f"ch_{name}_minutes"
        field_val = request.form.get(field_name)
        if field_val is not None and field_val != "":
            try:
                mins = float(field_val)
                if mins >= 0:
                    c["planned_minutes"] = mins
            except ValueError:
                pass  # ignore bad values, keep previous

        # Per-channel sub-exposure override
        sub_field = f"ch_{name}_subexp"
        sub_val = request.form.get(sub_field)
        if sub_val is not None and sub_val != "":
            try:
                sec = float(sub_val)  # Changed from int(float(sub_val)) to float(sub_val)
                if sec > 0:
                    c["sub_exposure_seconds"] = sec
            except ValueError:
                pass

    # Final total is sum of updated channels
    final_total = sum(c["planned_minutes"] for c in channels)

    # Recompute weights / fractions
    if final_total > 0:
        for c in channels:
            frac = c["planned_minutes"] / final_total
            c["weight_fraction"] = frac
            c["weight"] = frac
    else:
        for c in channels:
            c["weight_fraction"] = 0.0
            c["weight"] = 0.0

    data["channels"] = channels
    data["total_planned_minutes"] = round(final_total)

    # Dominant channel = one with max planned minutes
    if channels:
        dom = max(channels, key=lambda c: c.get("planned_minutes", 0))
        data["dominant_channel"] = dom.get("name", data.get("dominant_channel", ""))

    # Save back to plan
    plan.plan_json = json.dumps(data, indent=2)
    db.session.commit()

    flash("Plan updated.", "success")
    return redirect(url_for("target_detail", target_id=target.id))



@app.route("/target/<int:target_id>/progress/add", methods=["POST"])
def add_progress(target_id):
    target = Target.query.get_or_404(target_id)
    channel = request.form.get("channel").strip().upper()
    sub_exposure_seconds = float(request.form.get("sub_exposure_seconds"))
    sub_count = int(request.form.get("sub_count"))
    notes = request.form.get("notes")
    
    # Parse the imaging date
    imaging_date_str = request.form.get("imaging_date")
    if imaging_date_str:
        from datetime import datetime as dt
        imaging_date = dt.strptime(imaging_date_str, '%Y-%m-%d').date()
    else:
        imaging_date = datetime.now().date()

    session = ImagingSession(
        target_id=target.id,
        channel=channel,
        sub_exposure_seconds=sub_exposure_seconds,
        sub_count=sub_count,
        notes=notes,
        date=imaging_date,
    )
    db.session.add(session)
    db.session.commit()

    if target.calibration_tracking_enabled:
        plan = (
            TargetPlan.query
            .filter_by(target_id=target.id, palette_name=target.preferred_palette)
            .order_by(TargetPlan.created_at.desc())
            .first()
        )
        plan_data = json.loads(plan.plan_json) if plan else None
        from collections import defaultdict
        progress_seconds = defaultdict(float)
        for s in target.sessions:
            progress_seconds[s.channel] += s.sub_exposure_seconds * s.sub_count
        cal_config = get_effective_calibration_config(target)
        payload = get_calibration_payload(
            cal_config,
            plan_data,
            progress_seconds,
            target.calibration_captures,
            target.calibration_checkpoint_skips,
        )
        flash_msg = format_suggestion_flash(payload["suggestions"])
        if flash_msg:
            flash(
                f"Calibration reminder — {flash_msg}. Log captures below or skip for later.",
                "info",
            )

    flash("Progress added.", "success")
    return redirect(url_for("target_detail", target_id=target.id))


@app.route("/session/<int:session_id>/edit", methods=["GET", "POST"])
def edit_session(session_id):
    """Edit an imaging session."""
    session = ImagingSession.query.get_or_404(session_id)
    target = session.target
    
    if request.method == "POST":
        # Update session with form data
        session.channel = request.form.get("channel").strip().upper()
        session.sub_exposure_seconds = float(request.form.get("sub_exposure_seconds"))
        session.sub_count = int(request.form.get("sub_count"))
        session.notes = request.form.get("notes")
        
        # Parse the imaging date
        imaging_date_str = request.form.get("imaging_date")
        if imaging_date_str:
            from datetime import datetime as dt
            session.date = dt.strptime(imaging_date_str, '%Y-%m-%d').date()
        
        db.session.commit()
        flash("Session updated successfully.", "success")
        return redirect(url_for("target_detail", target_id=target.id))
    
    # GET request - show edit form
    # Get all channel names from target plan for dropdown
    channels = []
    plan = (
        TargetPlan.query
        .filter_by(target_id=target.id, palette_name=target.preferred_palette)
        .order_by(TargetPlan.created_at.desc())
        .first()
    )
    if plan:
        plan_data = json.loads(plan.plan_json)
        channels = [
            ch.get("name")
            for ch in plan_data.get("channels", [])
            if ch.get("name")
        ]
    
    return render_template("edit_session.html", session=session, target=target, channels=channels)


@app.route("/session/<int:session_id>/delete", methods=["POST"])
def delete_session(session_id):
    """Delete an imaging session."""
    session = ImagingSession.query.get_or_404(session_id)
    target_id = session.target_id
    
    db.session.delete(session)
    db.session.commit()
    
    flash("Session deleted successfully.", "success")
    return redirect(url_for("target_detail", target_id=target_id))


def _wants_json_response():
    """True for fetch/XHR requests expecting JSON instead of a redirect."""
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]


def _build_calibration_api_response(target):
    """Shared calibration payload for JSON API and AJAX actions."""
    from collections import defaultdict

    plan = (
        TargetPlan.query
        .filter_by(target_id=target.id, palette_name=target.preferred_palette)
        .order_by(TargetPlan.created_at.desc())
        .first()
    )
    plan_data = json.loads(plan.plan_json) if plan else None

    progress_seconds = defaultdict(float)
    for s in target.sessions:
        progress_seconds[s.channel] += s.sub_exposure_seconds * s.sub_count

    cal_config = get_effective_calibration_config(target)
    payload = get_calibration_payload(
        cal_config,
        plan_data,
        progress_seconds,
        target.calibration_captures,
        target.calibration_checkpoint_skips,
    )
    payload["skips"] = [
        {
            "id": skip.id,
            "channel": skip.channel,
            "frame_type": skip.frame_type,
            "checkpoint": skip.checkpoint,
        }
        for skip in target.calibration_checkpoint_skips
    ]
    payload["badges"] = channel_calibration_badges(
        cal_config,
        plan_data,
        progress_seconds,
        target.calibration_captures,
        target.calibration_checkpoint_skips,
    )
    payload["enabled"] = cal_config["enabled"]
    return payload


@app.route("/target/<int:target_id>/calibration/log", methods=["POST"])
def log_calibration_capture(target_id):
    target = Target.query.get_or_404(target_id)
    if not target.calibration_tracking_enabled:
        flash("Calibration tracking is not enabled for this target.", "warning")
        return redirect(url_for("target_detail", target_id=target.id))

    frame_type = (request.form.get("frame_type") or "").strip().lower()
    if frame_type not in ("dark", "flat", "dark_flat", "bias"):
        flash("Invalid calibration frame type.", "danger")
        return redirect(url_for("target_detail", target_id=target.id))

    channel = (request.form.get("channel") or "").strip().upper() or None
    if frame_type in ("flat", "dark_flat") and not channel:
        flash("Channel is required for flats and dark flats.", "danger")
        return redirect(url_for("target_detail", target_id=target.id))
    if frame_type in ("dark", "bias"):
        channel = None

    sub_exposure_seconds = None
    if frame_type == "dark":
        sub_raw = (request.form.get("sub_exposure_seconds") or "").strip()
        if not sub_raw:
            flash("Sub-exposure duration is required for darks (match your light frame length).", "danger")
            return redirect(url_for("target_detail", target_id=target.id))
        try:
            sub_exposure_seconds = float(sub_raw)
        except (TypeError, ValueError):
            flash("Invalid sub-exposure duration for darks.", "danger")
            return redirect(url_for("target_detail", target_id=target.id))
        if sub_exposure_seconds <= 0:
            flash("Sub-exposure duration must be greater than zero.", "danger")
            return redirect(url_for("target_detail", target_id=target.id))

    try:
        frame_count = int(request.form.get("frame_count", 0))
    except (TypeError, ValueError):
        frame_count = 0
    if frame_count <= 0:
        flash("Frame count must be greater than zero.", "danger")
        return redirect(url_for("target_detail", target_id=target.id))

    checkpoint = (request.form.get("checkpoint") or "manual").strip().lower()
    if checkpoint not in ("midpoint", "end", "manual"):
        checkpoint = "manual"

    imaging_date_str = request.form.get("imaging_date")
    if imaging_date_str:
        from datetime import datetime as dt
        capture_date = dt.strptime(imaging_date_str, "%Y-%m-%d").date()
    else:
        capture_date = datetime.now().date()

    capture = CalibrationCapture(
        target_id=target.id,
        date=capture_date,
        frame_type=frame_type,
        channel=channel,
        sub_exposure_seconds=sub_exposure_seconds,
        checkpoint=checkpoint,
        frame_count=frame_count,
        notes=request.form.get("notes"),
    )
    db.session.add(capture)
    db.session.commit()
    flash("Calibration capture logged.", "success")
    return redirect(url_for("target_detail", target_id=target.id))


@app.route("/target/<int:target_id>/calibration/skip", methods=["POST"])
def skip_calibration_checkpoint(target_id):
    target = Target.query.get_or_404(target_id)
    channel = (request.form.get("channel") or "").strip().upper()
    frame_type = (request.form.get("frame_type") or "").strip().lower()
    checkpoint = (request.form.get("checkpoint") or "").strip().lower()

    if frame_type not in ("flat", "dark_flat") or checkpoint != "end":
        message = "Invalid skip request."
        if _wants_json_response():
            return jsonify({"ok": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for("target_detail", target_id=target.id))

    existing = CalibrationCheckpointSkip.query.filter_by(
        target_id=target.id,
        channel=channel,
        frame_type=frame_type,
        checkpoint=checkpoint,
    ).first()
    if not existing:
        db.session.add(
            CalibrationCheckpointSkip(
                target_id=target.id,
                channel=channel,
                frame_type=frame_type,
                checkpoint=checkpoint,
            )
        )
        db.session.commit()
    message = f"Skipped {frame_type.replace('_', ' ')} {checkpoint} for {channel}."
    if _wants_json_response():
        db.session.refresh(target)
        return jsonify({
            "ok": True,
            "message": message,
            "calibration": _build_calibration_api_response(target),
        })
    flash(message, "info")
    return redirect(url_for("target_detail", target_id=target.id))


@app.route("/calibration/skip/<int:skip_id>/restore", methods=["POST"])
def restore_calibration_checkpoint(skip_id):
    skip = CalibrationCheckpointSkip.query.get_or_404(skip_id)
    target_id = skip.target_id
    label = (
        f"{skip.frame_type.replace('_', ' ')} {skip.checkpoint} for {skip.channel}"
    )
    db.session.delete(skip)
    db.session.commit()
    message = f"Restored calibration suggestion: {label}."
    if _wants_json_response():
        target = Target.query.get_or_404(target_id)
        return jsonify({
            "ok": True,
            "message": message,
            "calibration": _build_calibration_api_response(target),
        })
    flash(message, "success")
    return redirect(url_for("target_detail", target_id=target_id))


@app.route("/calibration/<int:capture_id>/edit", methods=["GET", "POST"])
def edit_calibration_capture(capture_id):
    capture = CalibrationCapture.query.get_or_404(capture_id)
    target = capture.target

    if request.method == "POST":
        frame_type = (request.form.get("frame_type") or capture.frame_type).strip().lower()
        if frame_type not in ("dark", "flat", "dark_flat", "bias"):
            flash("Invalid calibration frame type.", "danger")
            return redirect(url_for("edit_calibration_capture", capture_id=capture.id))

        channel = (request.form.get("channel") or "").strip().upper() or None
        if frame_type in ("flat", "dark_flat") and not channel:
            flash("Channel is required for flats and dark flats.", "danger")
            return redirect(url_for("edit_calibration_capture", capture_id=capture.id))
        if frame_type in ("dark", "bias"):
            channel = None

        sub_exposure_seconds = capture.sub_exposure_seconds
        if frame_type == "dark":
            sub_raw = (request.form.get("sub_exposure_seconds") or "").strip()
            if not sub_raw:
                flash("Sub-exposure duration is required for darks.", "danger")
                return redirect(url_for("edit_calibration_capture", capture_id=capture.id))
            try:
                sub_exposure_seconds = float(sub_raw)
            except (TypeError, ValueError):
                flash("Invalid sub-exposure duration.", "danger")
                return redirect(url_for("edit_calibration_capture", capture_id=capture.id))
        elif frame_type != "dark":
            sub_exposure_seconds = None

        capture.frame_type = frame_type
        capture.channel = channel
        capture.sub_exposure_seconds = sub_exposure_seconds
        capture.frame_count = int(request.form.get("frame_count", capture.frame_count))
        capture.notes = request.form.get("notes")
        checkpoint = (request.form.get("checkpoint") or "manual").strip().lower()
        capture.checkpoint = checkpoint if checkpoint in ("midpoint", "end", "manual") else "manual"

        imaging_date_str = request.form.get("imaging_date")
        if imaging_date_str:
            from datetime import datetime as dt
            capture.date = dt.strptime(imaging_date_str, "%Y-%m-%d").date()

        db.session.commit()
        flash("Calibration capture updated.", "success")
        return redirect(url_for("target_detail", target_id=target.id))

    channels, sub_exposures, _plan_data = get_target_plan_form_context(target)

    return render_template(
        "edit_calibration.html",
        capture=capture,
        target=target,
        channels=channels,
        sub_exposures=sub_exposures,
    )


@app.route("/calibration/<int:capture_id>/delete", methods=["POST"])
def delete_calibration_capture(capture_id):
    capture = CalibrationCapture.query.get_or_404(capture_id)
    target_id = capture.target_id
    db.session.delete(capture)
    db.session.commit()
    flash("Calibration capture deleted.", "success")
    return redirect(url_for("target_detail", target_id=target_id))


@app.route("/api/target/<int:target_id>/calibration")
def api_target_calibration(target_id):
    target = Target.query.get_or_404(target_id)
    return jsonify(_build_calibration_api_response(target))


@app.route("/imaging-logs")
def imaging_logs():
    """Display light sessions and calibration captures grouped by date."""
    sessions = (
        ImagingSession.query
        .join(Target)
        .order_by(ImagingSession.date.desc(), ImagingSession.id.desc())
        .all()
    )
    captures = (
        CalibrationCapture.query
        .join(Target)
        .order_by(CalibrationCapture.date.desc(), CalibrationCapture.id.desc())
        .all()
    )

    grouped_log_days = build_global_imaging_log_days(sessions, captures)

    session_dates = {s.date for s in sessions}
    capture_dates = {c.date for c in captures}
    unique_dates = session_dates | capture_dates
    unique_targets = {s.target_id for s in sessions} | {c.target_id for c in captures}

    stats = {
        "total_sessions": len(sessions),
        "total_calibration_captures": len(captures),
        "imaging_days": len(unique_dates),
        "targets_imaged": len(unique_targets),
    }

    return render_template(
        "imaging_logs.html",
        grouped_log_days=grouped_log_days,
        stats=stats,
    )


@app.route("/target/<int:target_id>/upload-final", methods=["POST"])
def upload_final_image(target_id):
    target = Target.query.get_or_404(target_id)
    file = request.files.get("final_image")
    if not file:
        flash("No file uploaded.", "danger")
        return redirect(url_for("target_detail", target_id=target.id))

    filename = secure_filename(file.filename)
    if not filename:
        flash("Invalid filename.", "danger")
        return redirect(url_for("target_detail", target_id=target.id))

    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(save_path)

    target.final_image_filename = filename
    db.session.commit()

    flash("Final image uploaded.", "success")
    return redirect(url_for("target_detail", target_id=target.id))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/api/resolve", methods=["GET"])
def api_resolve():
    """Resolve an object name to RA/Dec + enriched metadata.

    Uses the resolver chain (local catalogs → SIMBAD/NED/VizieR → Sesame).
    Response includes legacy fields (``name``, ``ra_hours``, ``dec_deg``,
    ``suggested_type``) plus enriched fields (``canonical_name``,
    ``common_names``, ``object_type``, ``magnitude``, ``source``,
    ``confidence``, ``matched_variant``, ``cached``, ``differs_from_input``).
    """
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Missing 'name' query parameter."}), 400

    from astro_utils import resolve_target_full

    try:
        obj = resolve_target_full(name)
    except RuntimeError as e:
        return jsonify({"error": str(e), "name": name}), 400
    except Exception as e:
        return jsonify({"error": f"Resolution failed: {e}", "name": name}), 500

    payload = obj.to_api_dict()
    # If the resolver could not determine a target_type (e.g. Sesame
    # fallback), enrich via the existing catalog-prefix detector so the
    # frontend still gets a sensible default.
    if payload.get("suggested_type") in (None, "", "other"):
        detected = detect_target_type(obj.canonical_name or name)
        if detected:
            payload["suggested_type"] = detected
    return jsonify(payload)


@app.route("/api/resolve/health", methods=["GET"])
def api_resolve_health():
    """Diagnostic endpoint for the resolver subsystem.

    Reports each chain source's availability and cache statistics.
    Useful when the user wants to verify offline mode, missing
    astroquery installs, or stale cache contents.
    """
    from resolver import get_default_chain
    chain = get_default_chain()
    sources_info = []
    for src in chain.resolvers:
        try:
            available = bool(src.is_available())
        except Exception as exc:
            available = False
            src_error = str(exc)
        else:
            src_error = None
        sources_info.append({
            "name": src.name,
            "requires_network": src.requires_network,
            "default_confidence": src.default_confidence,
            "available": available,
            "error": src_error,
        })

    cache_stats = {"total": 0, "positive": 0, "negative": 0}
    try:
        cache_stats["total"] = ResolverCache.query.count()
        cache_stats["negative"] = ResolverCache.query.filter_by(negative=True).count()
        cache_stats["positive"] = cache_stats["total"] - cache_stats["negative"]
    except Exception:
        pass

    cfg = GlobalConfig.query.first()
    settings = {
        "offline_mode": bool(getattr(cfg, "resolver_offline_mode", False)) if cfg else False,
        "enable_simbad": bool(getattr(cfg, "resolver_enable_simbad", True)) if cfg else True,
        "enable_ned":    bool(getattr(cfg, "resolver_enable_ned", True)) if cfg else True,
        "enable_vizier": bool(getattr(cfg, "resolver_enable_vizier", True)) if cfg else True,
        "enable_sesame": bool(getattr(cfg, "resolver_enable_sesame", True)) if cfg else True,
        "cache_ttl_days": int(getattr(cfg, "resolver_cache_ttl_days", 90)) if cfg else 90,
    }

    return jsonify({
        "sources": sources_info,
        "cache": cache_stats,
        "settings": settings,
    })


@app.route("/api/palette-recommendation", methods=["GET"])
def api_palette_recommendation():
    """Get recommended palette for a target type."""
    target_type = request.args.get("target_type", "").strip().lower()
    if not target_type:
        return jsonify({"error": "Missing 'target_type' query parameter."}), 400
    
    recommended_palette = get_recommended_palette(target_type)
    
    # Provide reasoning for the recommendation
    reasons = {
        "emission": "Emission nebulae work excellently with narrowband SHO filters",
        "diffuse": "Diffuse nebulae often benefit from HOO for enhanced contrast", 
        "reflection": "Reflection nebulae show great detail with broadband LRGB",
        "galaxy": "Galaxies typically use broadband LRGB for star colors and detail",
        "cluster": "Star clusters showcase natural colors best with LRGB",
        "planetary": "Planetary nebulae reveal structure well with narrowband SHO",
        "supernova_remnant": "Supernova remnants often have strong emission lines, perfect for SHO",
        "other": "SHO is a versatile starting point for most deep sky targets"
    }
    
    return jsonify({
        "target_type": target_type,
        "recommended_palette": recommended_palette,
        "reason": reasons.get(target_type, "Default recommendation")
    })


@app.route("/api/target/<int:target_id>/window", methods=["GET"])
def api_target_window(target_id):
    """Get real-time window calculation for a target."""
    target = Target.query.get_or_404(target_id)
    
    # Observer location and settings from config
    lat, lon, elev = get_observer_location()
    packup_time = parse_time_str(get_effective_packup_time(target))
    
    window_info = compute_target_window(
        ra_hours=target.ra_hours,
        dec_deg=target.dec_deg,
        latitude_deg=lat,
        longitude_deg=lon,
        elevation_m=elev,
        packup_time_local=packup_time,
        min_altitude_deg=get_effective_min_altitude(target),
    )
    
    return jsonify(window_info)


@app.route("/api/conditions/<int:target_id>")
def api_conditions(target_id):
    """Night conditions: moon phase, weather, seeing, channel suggestion."""
    from conditions_utils import get_tonight_conditions
    from collections import defaultdict

    lat, lon, elev = get_observer_location()
    config = get_global_config()
    tz_name = config.timezone_name or os.environ.get("OBSERVER_TZ", "Asia/Riyadh")

    plan_data = None
    progress_by_channel = None
    window_start_local = None
    window_end_local = None
    window_start_utc = None
    window_end_utc = None

    if target_id > 0:
        target = Target.query.get(target_id)
        if target:
            plan = (
                TargetPlan.query
                .filter_by(target_id=target.id, palette_name=target.preferred_palette)
                .order_by(TargetPlan.created_at.desc())
                .first()
            )
            plan_data = json.loads(plan.plan_json) if plan else None

            progress_by_channel = defaultdict(float)
            for s in target.sessions:
                progress_by_channel[s.channel] += (s.sub_exposure_seconds * s.sub_count) / 60.0
            progress_by_channel = dict(progress_by_channel)

            packup_time = parse_time_str(get_effective_packup_time(target))
            window_info = compute_target_window(
                ra_hours=target.ra_hours,
                dec_deg=target.dec_deg,
                latitude_deg=lat,
                longitude_deg=lon,
                elevation_m=elev,
                packup_time_local=packup_time,
                min_altitude_deg=get_effective_min_altitude(target),
            )
            if window_info.get("deps_available"):
                window_start_local = window_info.get("start_time_local")
                window_end_local = window_info.get("end_time_local")
                window_start_utc = window_info.get("start_time_utc")
                window_end_utc = window_info.get("end_time_utc")

    result = get_tonight_conditions(
        lat, lon, elev, tz_name,
        plan_data=plan_data,
        progress_by_channel=progress_by_channel,
        window_start_local=window_start_local,
        window_end_local=window_end_local,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        max_cloud_cover_pct=config.max_cloud_cover_pct or 25,
    )

    # Inject target context for Seeing Guide tab
    target_context = None
    if target_id > 0:
        tgt = Target.query.get(target_id)
        if tgt:
            type_name = tgt.target_type  # string column (backward compat)
            if not type_name and tgt.target_type_id:
                tt = TargetType.query.get(tgt.target_type_id)
                if tt:
                    type_name = tt.name
            target_context = {
                "target_name": tgt.name,
                "target_type": type_name,
            }
    result["target_context"] = target_context

    return jsonify(result)


@app.route("/settings", methods=["GET", "POST"])
def global_settings():
    """Manage global configuration settings."""
    config = get_global_config()
    
    if request.method == "POST":
        # Update global configuration
        config.observer_lat = float(request.form.get("observer_lat", config.observer_lat))
        config.observer_lon = float(request.form.get("observer_lon", config.observer_lon))
        config.observer_elev_m = float(request.form.get("observer_elev_m", config.observer_elev_m))
        config.default_packup_time = request.form.get("default_packup_time", config.default_packup_time)
        config.default_min_altitude = float(request.form.get("default_min_altitude", config.default_min_altitude))
        config.timezone_name = request.form.get("timezone_name", config.timezone_name)

        raw_cloud_pct = request.form.get("max_cloud_cover_pct", "").strip()
        if raw_cloud_pct:
            config.max_cloud_cover_pct = max(5, min(100, int(raw_cloud_pct)))

        config.default_calibration_darks = int(request.form.get("default_calibration_darks", 0) or 0)
        config.default_calibration_flats_per_channel = int(
            request.form.get("default_calibration_flats_per_channel", 0) or 0
        )
        config.default_calibration_dark_flats_per_channel = int(
            request.form.get("default_calibration_dark_flats_per_channel", 0) or 0
        )
        config.default_calibration_bias = int(request.form.get("default_calibration_bias", 0) or 0)

        # Resolver settings (Phase 8)
        config.resolver_offline_mode  = bool(request.form.get("resolver_offline_mode"))
        config.resolver_enable_simbad = bool(request.form.get("resolver_enable_simbad"))
        config.resolver_enable_ned    = bool(request.form.get("resolver_enable_ned"))
        config.resolver_enable_vizier = bool(request.form.get("resolver_enable_vizier"))
        config.resolver_enable_sesame = bool(request.form.get("resolver_enable_sesame"))
        try:
            ttl_days = int(request.form.get("resolver_cache_ttl_days", 90) or 90)
            config.resolver_cache_ttl_days = max(1, min(3650, ttl_days))
        except (TypeError, ValueError):
            pass
        # Rebuild the chain so toggle changes take effect immediately.
        try:
            from resolver import reset_default_chain
            reset_default_chain()
        except Exception:
            pass

        config.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            db.session.refresh(config)
            flash("Global settings updated successfully! All targets will use new defaults.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating settings: {e}", "error")
            
        return redirect(url_for("global_settings"))
    
    db.session.refresh(config)
    
    # Load available presets for the UI
    presets = []
    preset_dir = os.path.join(get_preset_dir(), 'filters')
    if os.path.exists(preset_dir):
        for filename in os.listdir(preset_dir):
            if filename.endswith('.json'):
                preset_path = os.path.join(preset_dir, filename)
                try:
                    data = load_preset_file(preset_path)
                    presets.append({
                        'key': filename.replace('.json', ''),
                        'name': data.get('preset_name', filename.replace('.json', '')),
                        'description': data.get('description', ''),
                        'filter_count': len(data.get('filters', [])),
                        'has_astrobin': any(f.get('astrobin_id') for f in data.get('filters', []))
                    })
                except Exception:
                    pass
    
    return render_template("settings.html", config=config, presets=presets)


@app.route("/settings/export-preset", methods=["POST"])
def export_preset_web():
    """Export current filters and optionally filter wheels as JSON."""
    include_wheels = request.form.get("include_wheels") == "1"
    
    filters = Filter.query.all()
    if not filters:
        flash("No filters found to export.", "warning")
        return redirect(url_for("global_settings"))
    
    export_data = {
        "preset_name": "Custom Export",
        "description": "Exported from ArmillaryLab",
        "filters": []
    }
    
    for f in filters:
        filter_data = {
            "name": f.name,
            "display_name": f.display_name,
            "filter_type": f.filter_type,
            "default_exposure": f.default_exposure
        }
        if f.astrobin_id:
            filter_data["astrobin_id"] = f.astrobin_id
        export_data["filters"].append(filter_data)
    
    if include_wheels:
        wheels = FilterWheel.query.all()
        export_data["filter_wheels"] = []
        for wheel in wheels:
            wheel_data = {
                "name": wheel.name,
                "slot_count": wheel.slot_count,
                "filter_size": wheel.filter_size,
                "is_default": wheel.is_default,
                "slots": []
            }
            for slot in wheel.slots:
                slot_data = {
                    "position": slot.position,
                    "filter_code": slot.filter.name if slot.filter else None,
                    "nina_name": slot.nina_filter_name
                }
                wheel_data["slots"].append(slot_data)
            export_data["filter_wheels"].append(wheel_data)
    
    # Create file for download
    output = io.BytesIO()
    output.write(json.dumps(export_data, indent=2).encode('utf-8'))
    output.seek(0)
    
    filename = f"armillarylab_preset_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return send_file(output, mimetype='application/json', as_attachment=True, download_name=filename)


@app.route("/settings/import-preset", methods=["POST"])
def import_preset_web():
    """Import filters and optionally filter wheels from JSON."""
    if 'preset_file' not in request.files:
        flash("No file uploaded.", "error")
        return redirect(url_for("global_settings"))
    
    file = request.files['preset_file']
    if file.filename == '':
        flash("No file selected.", "error")
        return redirect(url_for("global_settings"))
    
    try:
        import_data = json.load(file)
    except json.JSONDecodeError:
        flash("Invalid JSON file.", "error")
        return redirect(url_for("global_settings"))
    
    filters_data = import_data.get('filters', [])
    if not filters_data:
        flash("No filters found in import file.", "warning")
        return redirect(url_for("global_settings"))
    
    import_mode = request.form.get("import_mode", "merge")
    include_wheels = request.form.get("include_wheels") == "1"
    
    if import_mode == "replace":
        # Remove existing filters (and dependent wheel slots)
        FilterWheelSlot.query.delete()
        Filter.query.delete()
        db.session.commit()
    
    imported_count = 0
    updated_count = 0
    
    for f_data in filters_data:
        existing = Filter.query.filter_by(name=f_data['name']).first()
        
        if existing and import_mode == "merge":
            # Update existing filter
            existing.display_name = f_data.get('display_name', existing.display_name)
            existing.filter_type = f_data.get('filter_type', existing.filter_type)
            existing.default_exposure = f_data.get('default_exposure', existing.default_exposure)
            if 'astrobin_id' in f_data:
                existing.astrobin_id = f_data['astrobin_id']
            updated_count += 1
        elif not existing:
            # Create new filter
            filter_obj = Filter(
                name=f_data['name'],
                display_name=f_data.get('display_name', f_data['name']),
                filter_type=f_data.get('filter_type', 'other'),
                default_exposure=f_data.get('default_exposure', 300),
                astrobin_id=f_data.get('astrobin_id'),
                is_system=False,
                is_active=True
            )
            db.session.add(filter_obj)
            imported_count += 1
    
    db.session.commit()
    
    # Import filter wheels if requested
    wheel_count = 0
    if include_wheels and 'filter_wheels' in import_data:
        if import_mode == "replace":
            FilterWheel.query.delete()
            db.session.commit()
        
        wheels_data = import_data.get('filter_wheels', [])
        for wheel_data in wheels_data:
            wheel = FilterWheel(
                name=wheel_data['name'],
                slot_count=wheel_data.get('slot_count', 8),
                filter_size=wheel_data.get('filter_size', '1.25"'),
                is_active=True,
                is_default=wheel_data.get('is_default', False)
            )
            db.session.add(wheel)
            db.session.commit()
            
            for slot_data in wheel_data.get('slots', []):
                filter_obj = Filter.query.filter_by(name=slot_data.get('filter_code')).first() if slot_data.get('filter_code') else None
                slot = FilterWheelSlot(
                    filter_wheel_id=wheel.id,
                    filter_id=filter_obj.id if filter_obj else None,
                    position=slot_data['position'],
                    nina_filter_name=slot_data.get('nina_name')
                )
                db.session.add(slot)
            db.session.commit()
            wheel_count += 1
    
    if import_mode == "merge":
        flash(f"Import complete: {imported_count} new filters, {updated_count} updated, {wheel_count} filter wheel(s).", "success")
    else:
        flash(f"Imported {imported_count} filters and {wheel_count} filter wheel(s).", "success")
    
    return redirect(url_for("global_settings"))


@app.route("/settings/download-preset/<preset_name>")
def download_builtin_preset(preset_name):
    """Download a built-in preset file."""
    preset_path = os.path.join(get_preset_dir(), 'filters', f'{preset_name}.json')
    
    if not os.path.exists(preset_path):
        flash(f"Preset '{preset_name}' not found.", "error")
        return redirect(url_for("global_settings"))
    
    return send_file(preset_path, mimetype='application/json', as_attachment=True, 
                     download_name=f'{preset_name}_filters.json')


@app.route("/target/<int:target_id>/settings", methods=["GET", "POST"])
def target_settings(target_id):
    """Manage per-target configuration overrides."""
    target = Target.query.get_or_404(target_id)
    global_config = get_global_config()
    
    if request.method == "POST":
        # Update target overrides
        override_packup = request.form.get("override_packup_time", "").strip()
        override_altitude = request.form.get("override_min_altitude", "").strip()
        
        target.override_packup_time = override_packup if override_packup else None
        target.override_min_altitude = float(override_altitude) if override_altitude else None

        target.calibration_tracking_enabled = (
            request.form.get("calibration_tracking_enabled") == "1"
        )
        override_darks = request.form.get("override_calibration_darks", "").strip()
        override_flats = request.form.get("override_calibration_flats_per_channel", "").strip()
        override_dark_flats = request.form.get(
            "override_calibration_dark_flats_per_channel", ""
        ).strip()
        override_bias = request.form.get("override_calibration_bias", "").strip()

        target.override_calibration_darks = int(override_darks) if override_darks else None
        target.override_calibration_flats_per_channel = (
            int(override_flats) if override_flats else None
        )
        target.override_calibration_dark_flats_per_channel = (
            int(override_dark_flats) if override_dark_flats else None
        )
        target.override_calibration_bias = int(override_bias) if override_bias else None
        # Note: override_calibration_two_point column is retained but no longer
        # written from the UI (two-point nudge removed in v2.5.0). Column will
        # be dropped in v2.6.
        
        try:
            db.session.commit()
            flash("Target settings updated successfully! Window recalculated.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating target settings: {e}", "error")
        
        # Simple redirect back to target detail - window will be recalculated
        return redirect(url_for("target_detail", target_id=target_id))
    
    effective_calibration = get_effective_calibration_config(target)
    return render_template(
        "target_settings.html",
        target=target,
        global_config=global_config,
        effective_calibration=effective_calibration,
    )


@app.route("/manage-object-mappings", methods=["GET", "POST"])
def manage_object_mappings():
    """Manage object type mappings."""
    if request.method == "POST":
        object_name = request.form.get("object_name", "").strip()
        target_type_name = request.form.get("target_type_name")
        
        if object_name and target_type_name:
            success = add_object_mapping(object_name, target_type_name)
            if success:
                flash(f"Added mapping: {object_name} → {target_type_name}", "success")
            else:
                flash(f"Failed to add mapping (may already exist)", "error")
        else:
            flash("Please provide both object name and target type", "error")
        
        return redirect(url_for("manage_object_mappings"))
    
    # GET - show mappings
    mappings = ObjectMapping.query.join(TargetType).order_by(ObjectMapping.object_name).all()
    target_types = TargetType.query.order_by(TargetType.name).all()
    
    return render_template("manage_object_mappings.html", mappings=mappings, target_types=target_types)


@app.route("/palettes")
def palette_list():
    """List all palettes."""
    palettes = Palette.query.filter_by(is_active=True).order_by(Palette.is_system.desc(), Palette.name).all()
    return render_template("palette_list.html", palettes=palettes)


@app.route("/palette/new", methods=["GET", "POST"])
def new_palette():
    """Create a new custom palette."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        display_name = request.form.get("display_name", "").strip()
        description = request.form.get("description", "").strip()
        
        # Parse filter channels from form
        channels = []
        channel_count = int(request.form.get("channel_count", 0))
        
        for i in range(channel_count):
            channel_name = request.form.get(f"channel_{i}_name", "").strip()
            channel_label = request.form.get(f"channel_{i}_label", "").strip()
            channel_filter = request.form.get(f"channel_{i}_filter", "").strip()
            channel_rgb = request.form.get(f"channel_{i}_rgb_channel", "red")
            channel_exposure = int(request.form.get(f"channel_{i}_exposure", 300))
            channel_weight = float(request.form.get(f"channel_{i}_weight", 1.0))
            
            if channel_name and channel_label:
                channels.append({
                    "name": channel_name,
                    "label": channel_label,
                    "filter": channel_filter,
                    "rgb_channel": channel_rgb,
                    "default_exposure": channel_exposure,
                    "default_weight": channel_weight
                })
        
        if name and display_name and channels:
            try:
                palette = Palette(
                    name=name,
                    display_name=display_name,
                    description=description,
                    is_system=False,
                    is_active=True
                )
                palette.set_filters({"channels": channels})
                
                db.session.add(palette)
                db.session.commit()
                flash(f"Palette '{display_name}' created successfully!", "success")
                return redirect(url_for("palette_list"))
            except Exception as e:
                db.session.rollback()
                flash(f"Error creating palette: {e}", "error")
        else:
            flash("Please fill in all required fields and add at least one channel.", "error")
    
    return render_template("palette_form.html", palette=None)


@app.route("/palette/<int:palette_id>/edit", methods=["GET", "POST"])
def edit_palette(palette_id):
    """Edit an existing palette."""
    palette = Palette.query.get_or_404(palette_id)
    
    # Don't allow editing system palettes
    if palette.is_system:
        flash("System palettes cannot be edited.", "error")
        return redirect(url_for("palette_list"))
    
    if request.method == "POST":
        palette.display_name = request.form.get("display_name", "").strip()
        palette.description = request.form.get("description", "").strip()
        
        # Parse updated filter channels
        channels = []
        channel_count = int(request.form.get("channel_count", 0))
        
        for i in range(channel_count):
            channel_name = request.form.get(f"channel_{i}_name", "").strip()
            channel_label = request.form.get(f"channel_{i}_label", "").strip()
            channel_filter = request.form.get(f"channel_{i}_filter", "").strip()
            channel_rgb = request.form.get(f"channel_{i}_rgb_channel", "red")
            channel_exposure = int(request.form.get(f"channel_{i}_exposure", 300))
            channel_weight = float(request.form.get(f"channel_{i}_weight", 1.0))
            
            if channel_name and channel_label:
                channels.append({
                    "name": channel_name,
                    "label": channel_label,
                    "filter": channel_filter,
                    "rgb_channel": channel_rgb,
                    "default_exposure": channel_exposure,
                    "default_weight": channel_weight
                })
        
        if palette.display_name and channels:
            try:
                palette.set_filters({"channels": channels})
                db.session.commit()
                flash(f"Palette '{palette.display_name}' updated successfully!", "success")
                return redirect(url_for("palette_list"))
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating palette: {e}", "error")
        else:
            flash("Please fill in all required fields and add at least one channel.", "error")
    
    return render_template("palette_form.html", palette=palette)


@app.route("/palette/<int:palette_id>/delete", methods=["POST"])
def delete_palette(palette_id):
    """Delete a custom palette."""
    palette = Palette.query.get_or_404(palette_id)
    
    # Don't allow deleting system palettes
    if palette.is_system:
        flash("System palettes cannot be deleted.", "error")
        return redirect(url_for("palette_list"))
    
    # Check if any targets use this palette
    targets_using = Target.query.filter_by(palette_id=palette.id).count()
    if targets_using > 0:
        flash(f"Cannot delete palette - {targets_using} target(s) are using it.", "error")
        return redirect(url_for("palette_list"))
    
    try:
        db.session.delete(palette)
        db.session.commit()
        flash(f"Palette '{palette.display_name}' deleted successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting palette: {e}", "error")
    
    return redirect(url_for("palette_list"))


# ---------------------------------------------------------------------------
# FILTER MANAGEMENT ROUTES
# ---------------------------------------------------------------------------

@app.route("/filters")
def filter_list():
    """List all filters."""
    filters = Filter.query.order_by(Filter.is_system.desc(), Filter.name).all()
    
    # Load available presets for the Apply Preset modal
    presets = []
    preset_dir = os.path.join(get_preset_dir(), 'filters')
    if os.path.exists(preset_dir):
        for filename in os.listdir(preset_dir):
            if filename.endswith('.json'):
                preset_path = os.path.join(preset_dir, filename)
                try:
                    data = load_preset_file(preset_path)
                    presets.append({
                        'key': filename.replace('.json', ''),
                        'name': data.get('preset_name', filename.replace('.json', '')),
                        'has_astrobin': any(f.get('astrobin_id') for f in data.get('filters', []))
                    })
                except Exception:
                    pass
    
    return render_template("filter_list.html", filters=filters, presets=presets)


@app.route("/filters/apply-preset-ids", methods=["POST"])
def apply_preset_astrobin_ids():
    """Apply AstroBin IDs from a preset to existing filters."""
    preset_name = request.form.get("preset_name", "")
    
    preset_path = os.path.join(get_preset_dir(), 'filters', f'{preset_name}.json')
    if not os.path.exists(preset_path):
        flash(f"Preset '{preset_name}' not found.", "error")
        return redirect(url_for("filter_list"))
    
    try:
        preset_data = load_preset_file(preset_path)
        preset_filters = {f['name']: f.get('astrobin_id') for f in preset_data.get('filters', [])}
        
        updated_count = 0
        for filter_obj in Filter.query.all():
            if filter_obj.name in preset_filters and preset_filters[filter_obj.name]:
                filter_obj.astrobin_id = preset_filters[filter_obj.name]
                updated_count += 1
        
        db.session.commit()
        
        if updated_count > 0:
            flash(f"Updated AstroBin IDs for {updated_count} filter(s) from '{preset_name}' preset.", "success")
        else:
            flash("No matching filters found to update.", "warning")
            
    except Exception as e:
        db.session.rollback()
        flash(f"Error applying preset: {e}", "error")
    
    return redirect(url_for("filter_list"))


@app.route("/filter/new", methods=["GET", "POST"])
def new_filter():
    """Create a new custom filter."""
    if request.method == "POST":
        name = request.form.get("name", "").strip().upper()
        display_name = request.form.get("display_name", "").strip()
        filter_type = request.form.get("filter_type", "narrowband")
        default_exposure = int(request.form.get("default_exposure", 300))
        astrobin_id_str = request.form.get("astrobin_id", "").strip()
        astrobin_id = int(astrobin_id_str) if astrobin_id_str else None
        
        if name and display_name:
            # Check for duplicate name
            existing = Filter.query.filter_by(name=name).first()
            if existing:
                flash(f"A filter with code '{name}' already exists.", "error")
            else:
                try:
                    filter_obj = Filter(
                        name=name,
                        display_name=display_name,
                        filter_type=filter_type,
                        default_exposure=default_exposure,
                        astrobin_id=astrobin_id,
                        is_system=False,
                        is_active=True
                    )
                    db.session.add(filter_obj)
                    db.session.commit()
                    flash(f"Filter '{display_name}' created successfully!", "success")
                    return redirect(url_for("filter_list"))
                except Exception as e:
                    db.session.rollback()
                    flash(f"Error creating filter: {e}", "error")
        else:
            flash("Please fill in all required fields (name and display name).", "error")
    
    return render_template("filter_form.html", filter=None)


@app.route("/filter/<int:filter_id>/edit", methods=["GET", "POST"])
def edit_filter(filter_id):
    """Edit an existing filter."""
    filter_obj = Filter.query.get_or_404(filter_id)
    
    if request.method == "POST":
        # System filters can only change display_name, default_exposure, and astrobin_id
        if not filter_obj.is_system:
            new_name = request.form.get("name", "").strip().upper()
            # Check for duplicate if name changed
            if new_name != filter_obj.name:
                existing = Filter.query.filter_by(name=new_name).first()
                if existing:
                    flash(f"A filter with code '{new_name}' already exists.", "error")
                    return render_template("filter_form.html", filter=filter_obj)
            filter_obj.name = new_name
            filter_obj.filter_type = request.form.get("filter_type", "narrowband")
        
        filter_obj.display_name = request.form.get("display_name", "").strip()
        filter_obj.default_exposure = int(request.form.get("default_exposure", 300))
        
        # AstroBin ID can always be updated (even for system filters)
        astrobin_id_str = request.form.get("astrobin_id", "").strip()
        filter_obj.astrobin_id = int(astrobin_id_str) if astrobin_id_str else None
        
        if filter_obj.display_name:
            try:
                db.session.commit()
                flash(f"Filter '{filter_obj.display_name}' updated successfully!", "success")
                return redirect(url_for("filter_list"))
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating filter: {e}", "error")
        else:
            flash("Display name is required.", "error")
    
    return render_template("filter_form.html", filter=filter_obj)


@app.route("/filter/<int:filter_id>/delete", methods=["POST"])
def delete_filter(filter_id):
    """Delete or deactivate a filter."""
    filter_obj = Filter.query.get_or_404(filter_id)
    
    # System filters can only be deactivated, not deleted
    if filter_obj.is_system:
        filter_obj.is_active = not filter_obj.is_active
        status = "activated" if filter_obj.is_active else "deactivated"
        try:
            db.session.commit()
            flash(f"System filter '{filter_obj.display_name}' {status}.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating filter: {e}", "error")
    else:
        # Check if filter is used in any palette or wheel slot
        palette_usages = PaletteFilter.query.filter_by(filter_id=filter_id).count()
        slot_usages = FilterWheelSlot.query.filter_by(filter_id=filter_id).count()
        
        if palette_usages > 0 or slot_usages > 0:
            flash(f"Cannot delete filter - it's used in {palette_usages} palette(s) and {slot_usages} wheel slot(s).", "error")
        else:
            try:
                db.session.delete(filter_obj)
                db.session.commit()
                flash(f"Filter '{filter_obj.display_name}' deleted successfully!", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Error deleting filter: {e}", "error")
    
    return redirect(url_for("filter_list"))


@app.route("/api/filters")
def api_filters():
    """API endpoint returning all active filters as JSON."""
    filters = Filter.query.filter_by(is_active=True).order_by(Filter.name).all()
    return jsonify([{
        "id": f.id,
        "name": f.name,
        "display_name": f.display_name,
        "filter_type": f.filter_type,
        "default_exposure": f.default_exposure,
        "is_system": f.is_system
    } for f in filters])


# ---------------------------------------------------------------------------
# FILTER WHEEL MANAGEMENT ROUTES
# ---------------------------------------------------------------------------

@app.route("/filter-wheels")
def filter_wheel_list():
    """List all filter wheels."""
    wheels = FilterWheel.query.order_by(FilterWheel.is_active.desc(), FilterWheel.name).all()
    return render_template("filter_wheel_list.html", wheels=wheels)


@app.route("/filter-wheel/new", methods=["GET", "POST"])
def new_filter_wheel():
    """Create a new filter wheel."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        slot_count = int(request.form.get("slot_count", 8))
        filter_size = request.form.get("filter_size", "1.25\"").strip()
        nina_profile_name = request.form.get("nina_profile_name", "").strip() or None
        
        if name:
            try:
                wheel = FilterWheel(
                    name=name,
                    slot_count=slot_count,
                    filter_size=filter_size,
                    nina_profile_name=nina_profile_name,
                    is_active=False,
                    is_default=False
                )
                db.session.add(wheel)
                db.session.commit()
                
                # Create empty slots for the wheel
                for pos in range(slot_count):
                    slot = FilterWheelSlot(
                        filter_wheel_id=wheel.id,
                        filter_id=None,
                        position=pos
                    )
                    db.session.add(slot)
                db.session.commit()
                
                flash(f"Filter wheel '{name}' created successfully! Configure the slots below.", "success")
                return redirect(url_for("edit_filter_wheel", wheel_id=wheel.id))
            except Exception as e:
                db.session.rollback()
                flash(f"Error creating filter wheel: {e}", "error")
        else:
            flash("Please provide a name for the filter wheel.", "error")
    
    filters = Filter.query.filter_by(is_active=True).order_by(Filter.name).all()
    return render_template("filter_wheel_form.html", wheel=None, filters=filters)


@app.route("/filter-wheel/<int:wheel_id>/edit", methods=["GET", "POST"])
def edit_filter_wheel(wheel_id):
    """Edit a filter wheel and its slot assignments."""
    wheel = FilterWheel.query.get_or_404(wheel_id)
    
    if request.method == "POST":
        wheel.name = request.form.get("name", "").strip()
        wheel.filter_size = request.form.get("filter_size", "1.25\"").strip()
        wheel.nina_profile_name = request.form.get("nina_profile_name", "").strip() or None
        
        # Update slot assignments
        for slot in wheel.slots:
            filter_id_str = request.form.get(f"slot_{slot.position}_filter", "")
            filter_id = int(filter_id_str) if filter_id_str else None
            slot.filter_id = filter_id
            slot.nina_filter_name = request.form.get(f"slot_{slot.position}_nina_name", "").strip() or None
            slot.physical_filter_brand = request.form.get(f"slot_{slot.position}_brand", "").strip() or None
            slot.notes = request.form.get(f"slot_{slot.position}_notes", "").strip() or None
        
        try:
            db.session.commit()
            flash(f"Filter wheel '{wheel.name}' updated successfully!", "success")
            return redirect(url_for("filter_wheel_list"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating filter wheel: {e}", "error")
    
    filters = Filter.query.filter_by(is_active=True).order_by(Filter.name).all()
    return render_template("filter_wheel_form.html", wheel=wheel, filters=filters)


@app.route("/filter-wheel/<int:wheel_id>/delete", methods=["POST"])
def delete_filter_wheel(wheel_id):
    """Delete a filter wheel."""
    wheel = FilterWheel.query.get_or_404(wheel_id)
    
    # Don't allow deleting the active wheel
    if wheel.is_active:
        flash("Cannot delete the active filter wheel. Activate another wheel first.", "error")
        return redirect(url_for("filter_wheel_list"))
    
    try:
        db.session.delete(wheel)
        db.session.commit()
        flash(f"Filter wheel '{wheel.name}' deleted successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting filter wheel: {e}", "error")
    
    return redirect(url_for("filter_wheel_list"))


@app.route("/filter-wheel/<int:wheel_id>/activate", methods=["POST"])
def activate_filter_wheel(wheel_id):
    """Activate a filter wheel with validation against active target plans."""
    wheel = FilterWheel.query.get_or_404(wheel_id)
    
    # Get all filter codes available on this wheel
    wheel_filter_codes = set()
    for slot in wheel.slots:
        if slot.filter:
            wheel_filter_codes.add(slot.filter.name)
    
    # Check active target plans for filter compatibility
    affected_targets = []
    targets = Target.query.all()
    
    for target in targets:
        # Get the latest plan for this target
        plan = TargetPlan.query.filter_by(target_id=target.id).order_by(TargetPlan.created_at.desc()).first()
        if plan:
            try:
                plan_data = json.loads(plan.plan_json)
                channels = plan_data.get("channels", [])
                
                # Check each channel's filter
                missing_filters = []
                for ch in channels:
                    filter_name = ch.get("name", "")
                    # For custom filters, check mapped_filter_id or nina_filter
                    mapped_filter = ch.get("mapped_filter_id")
                    if mapped_filter:
                        mapped = Filter.query.get(mapped_filter)
                        if mapped and mapped.name not in wheel_filter_codes:
                            missing_filters.append(mapped.name)
                    elif filter_name not in wheel_filter_codes:
                        # Check if it's a standard filter
                        if Filter.query.filter_by(name=filter_name).first():
                            missing_filters.append(filter_name)
                
                if missing_filters:
                    affected_targets.append({
                        "target": target,
                        "missing_filters": list(set(missing_filters))
                    })
            except (json.JSONDecodeError, KeyError):
                pass
    
    # If there are affected targets and user hasn't confirmed, show warning
    if affected_targets and request.form.get("confirm") != "yes":
        return render_template("filter_wheel_activate_confirm.html", 
                             wheel=wheel, 
                             affected_targets=affected_targets)
    
    # Proceed with activation
    try:
        # Deactivate all other wheels
        FilterWheel.query.update({FilterWheel.is_active: False})
        
        # Activate selected wheel
        wheel.is_active = True
        db.session.commit()
        
        flash(f"Filter wheel '{wheel.name}' is now active!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error activating filter wheel: {e}", "error")
    
    return redirect(url_for("filter_wheel_list"))


@app.route("/api/active-wheel")
def api_active_wheel():
    """API endpoint returning the active filter wheel configuration."""
    wheel = FilterWheel.query.filter_by(is_active=True).first()
    if not wheel:
        return jsonify({"error": "No active filter wheel"}), 404
    
    slots = []
    for slot in wheel.slots:
        slots.append({
            "position": slot.position,
            "filter_id": slot.filter_id,
            "filter_name": slot.filter.name if slot.filter else None,
            "filter_display_name": slot.filter.display_name if slot.filter else None,
            "nina_filter_name": slot.nina_filter_name,
            "brand": slot.physical_filter_brand
        })
    
    return jsonify({
        "id": wheel.id,
        "name": wheel.name,
        "slot_count": wheel.slot_count,
        "filter_size": wheel.filter_size,
        "nina_profile_name": wheel.nina_profile_name,
        "slots": slots
    })


# ---------------------------------------------------------------------------
# CLI helpers - Preset System
# ---------------------------------------------------------------------------

def load_preset_file(preset_path):
    """Load a JSON preset file."""
    import json
    with open(preset_path, 'r') as f:
        return json.load(f)


def get_preset_dir():
    """Get the path to the presets directory."""
    return os.path.join(os.path.dirname(__file__), 'config', 'presets')


def list_filter_presets():
    """List available filter presets."""
    preset_dir = os.path.join(get_preset_dir(), 'filters')
    if not os.path.exists(preset_dir):
        return []
    return [f.replace('.json', '') for f in os.listdir(preset_dir) if f.endswith('.json')]


@app.cli.command("migrate-db")
def migrate_db():
    """Run additive schema migrations (never deletes rows).

    Run after upgrading ArmillaryLab when models gain columns/tables, or when
    the UI or SQL mentions missing tables/columns. Not required on every Flask
    start or after every backup restore; a DB that already matches this checkout
    is typically a no-op.

    Safe workflow:
      1. flask db info          # confirm which database file/server is active
      2. flask db backup        # snapshot before schema changes
      3. flask migrate-db       # add missing columns/tables only
    """
    import shutil
    from sqlalchemy import inspect, text
    from config.database import get_database_config
    from config.sqlite_health import check_sqlite_database, sqlite_has_core_schema, sqlite_db_info

    local_db_config = get_database_config(BASE_DIR)

    def row_counts():
        counts = {}
        for table in ("targets", "target_plans", "imaging_sessions", "filters"):
            try:
                counts[table] = db.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            except Exception:
                counts[table] = None
        return counts

    print(f"Database type: {local_db_config.db_type}")
    print(f"Connection: {local_db_config.connection_string}")

    backup_path = None

    if local_db_config.db_type == "sqlite":
        source_path = local_db_config.sqlite_file_path()
        if not source_path:
            print("ERROR: Could not resolve SQLite file path.")
            return

        ensure_sqlite_serving_ready()
        ok, msg, info = check_sqlite_database(source_path)
        print(msg)
        if not ok:
            print(
                "Cannot migrate until the database has a valid schema. "
                "Run: python scripts/diagnose_db.py"
            )
            return

        if info and info.get("valid") and info.get("imaging_sessions", 0) >= 0:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = source_path.parent / f"{source_path.name}.backup_{stamp}"
            shutil.copy2(source_path, backup_path)
            print(f"Auto-backup created: {backup_path}")
        else:
            info = sqlite_db_info(source_path)
            print(f"ERROR: Database still invalid after repair attempt: {info}")
            return

    elif local_db_config.db_type == "postgresql":
        valid, errors = local_db_config.validate_connection()
        if not valid:
            print(f"ERROR: Cannot connect to PostgreSQL: {errors}")
            return
        print("PostgreSQL connection verified.")

    before_counts = row_counts()
    if any(v is not None for v in before_counts.values()):
        print("Row counts before migration:", before_counts)

    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()

    if "targets" not in table_names:
        print(
            "ERROR: Core schema missing. "
            "Run 'flask init-db' to create the schema, then restore data."
        )
        return

    apply_additive_schema_migrations()

    after_counts = row_counts()
    if any(v is not None for v in after_counts.values()):
        print("Row counts after migration:", after_counts)
        for table in ("targets", "target_plans", "imaging_sessions"):
            if before_counts.get(table) is not None and after_counts.get(table) is not None:
                if after_counts[table] < before_counts[table]:
                    restore_hint = f"Restore from backup: {backup_path}" if backup_path else "Check your PostgreSQL backups."
                    print(
                        f"WARNING: {table} row count decreased "
                        f"({before_counts[table]} -> {after_counts[table]}). "
                        f"{restore_hint}"
                    )

    print("Database migration complete (additive only — no rows deleted).")


@app.cli.command("init-db")
@click.option('--mode', type=click.Choice(['starter', 'minimal']), default='starter',
              help='starter = full setup with all palettes/types/wheel; minimal = just filters')
@click.option('--filter-preset', '-f', default='generic',
              help='Filter preset to use (e.g., generic, zwo). Run "flask list-presets" to see available options.')
@click.option('--force', is_flag=True, help='Force re-initialization (drops existing data)')
def init_db(mode, filter_preset, force):
    """Initialize the database with configurable presets.
    
    Examples:
        flask init-db                          # Standard setup with generic filters
        flask init-db --filter-preset zwo      # Use ZWO filters with AstroBin IDs
        flask init-db --mode minimal           # Just filters, no palettes/wheels
        flask init-db --force                  # Reset and reinitialize
    """
    import json
    
    preset_dir = get_preset_dir()
    
    # Validate filter preset exists
    filter_preset_path = os.path.join(preset_dir, 'filters', f'{filter_preset}.json')
    if not os.path.exists(filter_preset_path):
        available = list_filter_presets()
        print(f"Error: Filter preset '{filter_preset}' not found.")
        print(f"Available presets: {', '.join(available)}")
        return
    
    # Load preset files
    base_preset_path = os.path.join(preset_dir, 'base.json')
    if not os.path.exists(base_preset_path):
        print("Error: base.json preset file not found. Creating with defaults...")
        # Fall back to hardcoded defaults if preset file missing
        base_preset = None
    else:
        base_preset = load_preset_file(base_preset_path)
    
    filter_preset_data = load_preset_file(filter_preset_path)

    if db_config.db_type == "sqlite":
        ensure_sqlite_serving_ready()

    # Handle force flag
    if force:
        from config.destructive_db_guard import destructive_db_allowed, destructive_db_allowed_pg

        if db_config.db_type == "sqlite":
            db_path = db_config.sqlite_file_path()
            allowed, refuse_msg = destructive_db_allowed(db_path, "flask init-db --force")
        else:
            allowed, refuse_msg = destructive_db_allowed_pg(db, "flask init-db --force")
        if not allowed:
            print(refuse_msg)
            return
        print("Force flag set - clearing existing data...")
        db.drop_all()
        db.create_all()
        print("Database schema recreated.")
    else:
        db.create_all()
    
    # Create default global config if none exists
    if not GlobalConfig.query.first():
        config = GlobalConfig()
        db.session.add(config)
        db.session.commit()
        print("Created default global configuration.")
    
    # Create filters from preset
    if not Filter.query.first():
        filters_data = filter_preset_data.get('filters', [])
        for f_data in filters_data:
            filter_obj = Filter(
                name=f_data["name"],
                display_name=f_data["display_name"],
                filter_type=f_data["filter_type"],
                default_exposure=f_data.get("default_exposure", 300),
                astrobin_id=f_data.get("astrobin_id"),
                is_system=True,
                is_active=True
            )
            db.session.add(filter_obj)
        
        db.session.commit()
        preset_name = filter_preset_data.get('preset_name', filter_preset)
        print(f"Created filters from '{preset_name}' preset ({len(filters_data)} filters).")
    else:
        print("Filters already exist - skipping. Use --force to reinitialize.")
    
    # For starter mode, also create palettes, target types, and filter wheel
    if mode == 'starter' and base_preset:
        # Create target types
        if not TargetType.query.first():
            target_types = base_preset.get('target_types', [])
            for tt_data in target_types:
                target_type = TargetType(
                    name=tt_data["name"],
                    recommended_palette=tt_data["recommended_palette"],
                    description=tt_data["description"]
                )
                db.session.add(target_type)
            db.session.commit()
            print(f"Created {len(target_types)} target types.")
        else:
            print("Target types already exist - skipping.")
        
        # Create palettes
        if not Palette.query.first():
            palettes = base_preset.get('palettes', [])
            for palette_data in palettes:
                palette = Palette(
                    name=palette_data["name"],
                    display_name=palette_data["display_name"],
                    description=palette_data["description"],
                    is_system=True,
                    is_active=True
                )
                palette.set_filters(palette_data["filters"])
                db.session.add(palette)
            db.session.commit()
            print(f"Created {len(palettes)} palettes.")
        else:
            print("Palettes already exist - skipping.")
        
        # Create filter wheel
        if not FilterWheel.query.first():
            wheel_data = base_preset.get('filter_wheel', {})
            wheel = FilterWheel(
                name=wheel_data.get('name', 'Default 8-Slot'),
                slot_count=wheel_data.get('slot_count', 8),
                filter_size=wheel_data.get('filter_size', '1.25"'),
                nina_profile_name=None,
                is_active=True,
                is_default=True
            )
            db.session.add(wheel)
            db.session.commit()
            
            # Create slots
            slots_data = wheel_data.get('slots', [])
            for slot_data in slots_data:
                filter_obj = Filter.query.filter_by(name=slot_data["filter_code"]).first()
                slot = FilterWheelSlot(
                    filter_wheel_id=wheel.id,
                    filter_id=filter_obj.id if filter_obj else None,
                    position=slot_data["position"],
                    nina_filter_name=slot_data["nina_name"]
                )
                db.session.add(slot)
            db.session.commit()
            print(f"Created filter wheel '{wheel.name}' with {len(slots_data)} slots.")
        else:
            print("Filter wheel already exists - skipping.")
    
    elif mode == 'minimal':
        print("Minimal mode - skipped palettes, target types, and filter wheel.")
    
    print(f"\nDatabase initialized successfully!")
    print(f"  Mode: {mode}")
    print(f"  Filter preset: {filter_preset}")


@app.cli.command("resolver-cache-purge")
def resolver_cache_purge():
    """Purge expired ResolverCache rows."""
    from resolver.cache import purge_expired
    removed = purge_expired()
    print(f"Removed {removed} expired ResolverCache row(s).")


@app.cli.command("resolver-cache-clear")
def resolver_cache_clear():
    """Delete ALL ResolverCache rows (positive + negative)."""
    from resolver.cache import clear_all
    removed = clear_all()
    print(f"Cleared {removed} ResolverCache row(s).")


@app.cli.command("resolver-test")
@click.argument("name")
def resolver_test(name):
    """Resolve an object name from the command line."""
    from astro_utils import resolve_target_full
    try:
        obj = resolve_target_full(name)
    except Exception as exc:
        print(f"FAILED: {exc}")
        return
    print(f"Canonical:    {obj.canonical_name}")
    print(f"RA / Dec:     {obj.ra_hours:.4f} h  /  {obj.dec_deg:+.4f}°")
    print(f"Object type:  {obj.object_type}")
    print(f"Target type:  {obj.target_type}")
    print(f"Source:       {obj.source}  (confidence={obj.confidence})")
    print(f"Cached:       {obj.cached}")
    if obj.catalog_aliases:
        print(f"Also catalogued as: {', '.join(obj.catalog_aliases[:6])}")
    if obj.common_names:
        print(f"Aliases:      {', '.join(obj.common_names[:5])}")


@app.cli.command("list-presets")
def list_presets():
    """List available filter presets."""
    import json
    
    presets = list_filter_presets()
    if not presets:
        print("No filter presets found in config/presets/filters/")
        return
    
    print("Available filter presets:")
    print("-" * 50)
    
    preset_dir = os.path.join(get_preset_dir(), 'filters')
    for preset_name in presets:
        preset_path = os.path.join(preset_dir, f'{preset_name}.json')
        try:
            data = load_preset_file(preset_path)
            display_name = data.get('preset_name', preset_name)
            desc = data.get('description', 'No description')
            filter_count = len(data.get('filters', []))
            has_astrobin = any(f.get('astrobin_id') for f in data.get('filters', []))
            astrobin_status = "✓ AstroBin IDs" if has_astrobin else "✗ No AstroBin IDs"
            
            print(f"\n  {preset_name}")
            print(f"    Name: {display_name}")
            print(f"    Filters: {filter_count}")
            print(f"    AstroBin: {astrobin_status}")
            print(f"    Description: {desc}")
        except Exception as e:
            print(f"\n  {preset_name} (error loading: {e})")
    
    print("\n" + "-" * 50)
    print("Usage: flask init-db --filter-preset <preset_name>")


@app.cli.command("export-preset")
@click.argument('output_file')
@click.option('--include-wheels', is_flag=True, help='Include filter wheel configurations')
def export_preset(output_file, include_wheels):
    """Export current filters (and optionally filter wheels) to a JSON preset file.
    
    Examples:
        flask export-preset my_filters.json
        flask export-preset my_setup.json --include-wheels
    """
    import json
    
    filters = Filter.query.all()
    if not filters:
        print("No filters found in database to export.")
        return
    
    export_data = {
        "preset_name": "Custom Export",
        "description": "Exported from database",
        "filters": []
    }
    
    for f in filters:
        filter_data = {
            "name": f.name,
            "display_name": f.display_name,
            "filter_type": f.filter_type,
            "default_exposure": f.default_exposure
        }
        if f.astrobin_id:
            filter_data["astrobin_id"] = f.astrobin_id
        export_data["filters"].append(filter_data)
    
    if include_wheels:
        wheels = FilterWheel.query.all()
        export_data["filter_wheels"] = []
        for wheel in wheels:
            wheel_data = {
                "name": wheel.name,
                "slot_count": wheel.slot_count,
                "filter_size": wheel.filter_size,
                "is_default": wheel.is_default,
                "slots": []
            }
            for slot in wheel.slots:
                slot_data = {
                    "position": slot.position,
                    "filter_code": slot.filter.name if slot.filter else None,
                    "nina_name": slot.nina_filter_name
                }
                wheel_data["slots"].append(slot_data)
            export_data["filter_wheels"].append(wheel_data)
    
    # Ensure output directory exists
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    with open(output_file, 'w') as f:
        json.dump(export_data, f, indent=2)
    
    print(f"Exported {len(filters)} filters to {output_file}")
    if include_wheels:
        print(f"  (including {len(wheels)} filter wheel(s))")


@app.cli.command("import-preset")
@click.argument('input_file')
@click.option('--merge', is_flag=True, help='Merge with existing filters (default replaces)')
@click.option('--include-wheels', is_flag=True, help='Also import filter wheel configurations')
def import_preset(input_file, merge, include_wheels):
    """Import filters from a JSON preset file.
    
    Examples:
        flask import-preset my_filters.json              # Replace existing filters
        flask import-preset my_filters.json --merge      # Add to existing filters
        flask import-preset my_setup.json --include-wheels
    """
    import json
    
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' not found.")
        return
    
    with open(input_file, 'r') as f:
        import_data = json.load(f)
    
    filters_data = import_data.get('filters', [])
    if not filters_data:
        print("No filters found in import file.")
        return
    
    if not merge:
        # Remove existing filters (and dependent wheel slots)
        FilterWheelSlot.query.delete()
        Filter.query.delete()
        db.session.commit()
        print("Cleared existing filters.")
    
    imported_count = 0
    updated_count = 0
    
    for f_data in filters_data:
        existing = Filter.query.filter_by(name=f_data['name']).first()
        
        if existing and merge:
            # Update existing filter
            existing.display_name = f_data.get('display_name', existing.display_name)
            existing.filter_type = f_data.get('filter_type', existing.filter_type)
            existing.default_exposure = f_data.get('default_exposure', existing.default_exposure)
            if 'astrobin_id' in f_data:
                existing.astrobin_id = f_data['astrobin_id']
            updated_count += 1
        elif not existing:
            # Create new filter
            filter_obj = Filter(
                name=f_data['name'],
                display_name=f_data.get('display_name', f_data['name']),
                filter_type=f_data.get('filter_type', 'other'),
                default_exposure=f_data.get('default_exposure', 300),
                astrobin_id=f_data.get('astrobin_id'),
                is_system=False,
                is_active=True
            )
            db.session.add(filter_obj)
            imported_count += 1
    
    db.session.commit()
    
    if merge:
        print(f"Import complete: {imported_count} new, {updated_count} updated")
    else:
        print(f"Imported {imported_count} filters")
    
    # Import filter wheels if requested
    if include_wheels and 'filter_wheels' in import_data:
        if not merge:
            FilterWheel.query.delete()
            db.session.commit()
        
        wheels_data = import_data.get('filter_wheels', [])
        for wheel_data in wheels_data:
            wheel = FilterWheel(
                name=wheel_data['name'],
                slot_count=wheel_data.get('slot_count', 8),
                filter_size=wheel_data.get('filter_size', '1.25"'),
                is_active=True,
                is_default=wheel_data.get('is_default', False)
            )
            db.session.add(wheel)
            db.session.commit()
            
            for slot_data in wheel_data.get('slots', []):
                filter_obj = Filter.query.filter_by(name=slot_data.get('filter_code')).first() if slot_data.get('filter_code') else None
                slot = FilterWheelSlot(
                    filter_wheel_id=wheel.id,
                    filter_id=filter_obj.id if filter_obj else None,
                    position=slot_data['position'],
                    nina_filter_name=slot_data.get('nina_name')
                )
                db.session.add(slot)
            db.session.commit()
            print(f"  Imported filter wheel: {wheel.name}")
        
        print(f"Imported {len(wheels_data)} filter wheel(s)")


if __name__ == "__main__":
    # For local dev. In Docker/K8s use gunicorn or `flask run`.
    os.environ.setdefault("ARMILLARYLAB_SERVE", "1")
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True,
    )