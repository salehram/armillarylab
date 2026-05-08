import csv
import click

from datetime import datetime, time, timezone, timedelta
import os
import io
import json

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_from_directory, jsonify,
    send_file
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from werkzeug.utils import secure_filename

from astro_utils import (
    compute_target_window,
    build_default_plan_json,
)

from nina_integration import load_nina_template, build_nina_sequence_from_blocks
from time_utils import register_time_filters, format_hms, parse_hms, hms_to_minutes
from zoneinfo import ZoneInfo

# Import database configuration
from config.database import get_flask_config

# Import CLI commands
from cli import register_cli_commands

# Application version
APP_VERSION = "2.0.0-dev"
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

db = SQLAlchemy(app)

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
    
    # Timezone
    timezone_name = db.Column(db.String(64), default="Asia/Riyadh")
    
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
    darks = request.form.get("darks", "")
    flats = request.form.get("flats", "")
    flat_darks = request.form.get("flat_darks", "")
    bias = request.form.get("bias", "")
    
    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    header = ["date", "filter", "number", "duration", "binning", "gain", "sensorCooling"]
    if darks:
        header.append("darks")
    if flats:
        header.append("flats")
    if flat_darks:
        header.append("flatDarks")
    if bias:
        header.append("bias")
    if bortle:
        header.append("bortle")
    writer.writerow(header)
    
    # Group sessions by date and BASE filter to consolidate
    # Map channel names to their base filter names
    from collections import defaultdict
    sessions_grouped = defaultdict(lambda: {"number": 0, "duration": None})
    
    for session in target.sessions:
        # Map channel name to base filter name
        base_filter = filter_name_map.get(session.channel, session.channel)
        key = (session.date.strftime("%Y-%m-%d"), base_filter, session.sub_exposure_seconds)
        sessions_grouped[key]["number"] += session.sub_count
        sessions_grouped[key]["duration"] = session.sub_exposure_seconds
    
    # Track filters missing AstroBin IDs
    filters_missing_ids = []
    
    # Write rows
    for (date, filter_name, duration), data in sorted(sessions_grouped.items()):
        # Use AstroBin ID if available, otherwise use filter name as fallback
        filter_value = astrobin_id_map.get(filter_name, filter_name)
        if filter_name not in astrobin_id_map and filter_name not in filters_missing_ids:
            filters_missing_ids.append(filter_name)
        
        row = [
            date,
            filter_value,
            data["number"],
            duration,
            binning,
            gain,
            sensor_cooling
        ]
        if darks:
            row.append(darks)
        if flats:
            row.append(flats)
        if flat_darks:
            row.append(flat_darks)
        if bias:
            row.append(bias)
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

    # Original total (from plan or sum of channels)
    orig_total = data.get("total_planned_minutes")
    if not orig_total:
        orig_total = sum(float(c.get("planned_minutes", 0) or 0) for c in channels)

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

    # User-specified total
    form_total_raw = request.form.get("total_planned_minutes")
    new_total = None
    if form_total_raw:
        try:
            new_total = float(form_total_raw)
        except ValueError:
            new_total = None

    # If user provided a new total, rescale channels proportionally first
    if new_total and new_total > 0 and orig_total and orig_total > 0:
        scale = new_total / orig_total
        for c in channels:
            c["planned_minutes"] = c["planned_minutes"] * scale

    # Then apply per-channel overrides from the form
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
    if target.plans:
        plan = target.plans[0]  # Get the first/main plan
        plan_data = json.loads(plan.plan_json)
        for channel_name in plan_data.keys():
            channels.append(channel_name)
    
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


@app.route("/imaging-logs")
def imaging_logs():
    """Display all imaging sessions grouped by date to track imaging days."""
    sessions = (
        ImagingSession.query
        .join(Target)
        .order_by(ImagingSession.date.desc(), ImagingSession.id.desc())
        .all()
    )
    
    # Group sessions by date
    from collections import defaultdict
    sessions_by_date = defaultdict(list)
    
    for session in sessions:
        sessions_by_date[session.date].append(session)
    
    # Convert to list of tuples for template
    grouped_sessions = sorted(sessions_by_date.items(), key=lambda x: x[0], reverse=True)
    
    # Calculate some statistics
    total_sessions = len(sessions)
    unique_dates = len(sessions_by_date)
    unique_targets = len(set(session.target_id for session in sessions))
    
    stats = {
        'total_sessions': total_sessions,
        'imaging_days': unique_dates,
        'targets_imaged': unique_targets
    }
    
    return render_template("imaging_logs.html", 
                         grouped_sessions=grouped_sessions,
                         stats=stats)


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
    """Resolve an object name to RA/Dec via astro_utils.resolve_target_name."""
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Missing 'name' query parameter."}), 400

    from astro_utils import resolve_target_name

    try:
        ra_hours, dec_deg = resolve_target_name(name)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # Unexpected errors
        return jsonify({"error": f"Resolution failed: {e}"}), 500

    # Attempt to determine target type from catalog designation
    detected_type = detect_target_type(name)

    return jsonify({
        "name": name,
        "ra_hours": ra_hours,
        "dec_deg": dec_deg,
        "suggested_type": detected_type
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
        config.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash("Global settings updated successfully! All targets will use new defaults.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating settings: {e}", "error")
            
        return redirect(url_for("global_settings"))
    
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
        
        try:
            db.session.commit()
            flash("Target settings updated successfully! Window recalculated.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating target settings: {e}", "error")
        
        # Simple redirect back to target detail - window will be recalculated
        return redirect(url_for("target_detail", target_id=target_id))
    
    return render_template("target_settings.html", target=target, global_config=global_config)


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
    """Run database migrations for schema changes."""
    from sqlalchemy import inspect, text
    
    inspector = inspect(db.engine)
    
    # Check if filters table exists
    if 'filters' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('filters')]
        
        # Add astrobin_id column if it doesn't exist
        if 'astrobin_id' not in columns:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE filters ADD COLUMN astrobin_id INTEGER'))
                conn.commit()
            print("Added 'astrobin_id' column to filters table.")
        else:
            print("Column 'astrobin_id' already exists in filters table.")
    else:
        print("Table 'filters' does not exist. Run 'flask init-db' first.")
    
    print("Database migration complete.")


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
    
    # Handle force flag
    if force:
        print("Force flag set - clearing existing data...")
        # Drop all tables and recreate - cleanest approach
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)