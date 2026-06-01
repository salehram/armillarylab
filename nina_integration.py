from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import List, Dict, Any, Optional

# Configure logging
logger = logging.getLogger(__name__)

# Legacy filter wheel mapping (used as fallback)
# Channels here are the short codes used in your planner: H, O, S, L, R, G, B, LP
FILTER_CONFIG: dict[str, dict[str, int | str]] = {
    "LP": {"nina_name": "LP",   "position": 0},
    "L":  {"nina_name": "L",    "position": 1},
    "R":  {"nina_name": "R",    "position": 2},
    "G":  {"nina_name": "G",    "position": 3},
    "B":  {"nina_name": "B",    "position": 4},
    "H":  {"nina_name": "Ha",   "position": 5},   # Ha
    "S":  {"nina_name": "SII",  "position": 6},   # SII
    "O":  {"nina_name": "OIII", "position": 7},   # OIII
}


def get_active_wheel_config() -> Optional[Dict[str, Dict[str, Any]]]:
    """
    Get filter configuration from the active filter wheel in the database.
    Returns a dict mapping filter codes to {nina_name, position}.
    Returns None if no active wheel or database not available.
    """
    try:
        # Import here to avoid circular imports
        from app import db, FilterWheel, FilterWheelSlot
        
        wheel = FilterWheel.query.filter_by(is_active=True).first()
        if not wheel:
            logger.warning("No active filter wheel found, using legacy FILTER_CONFIG")
            return None
        
        config = {}
        for slot in wheel.slots:
            if slot.filter:
                filter_code = slot.filter.name
                nina_name = slot.nina_filter_name or filter_code
                config[filter_code] = {
                    "nina_name": nina_name,
                    "position": slot.position
                }
        
        logger.info(f"Using active filter wheel '{wheel.name}' with {len(config)} filters")
        return config
        
    except Exception as e:
        logger.warning(f"Could not load active wheel config: {e}, using legacy FILTER_CONFIG")
        return None


def get_filter_config() -> Dict[str, Dict[str, Any]]:
    """
    Get filter configuration, preferring active wheel from database,
    falling back to legacy FILTER_CONFIG.
    """
    wheel_config = get_active_wheel_config()
    if wheel_config:
        return wheel_config
    return FILTER_CONFIG


def _deep_clone(obj: Any) -> Any:
    """Clone using JSON round-trip to avoid sharing references."""
    return json.loads(json.dumps(obj))


def load_nina_template(path: str | Path = "nina_template.json") -> dict:
    """
    Load a NINA advanced sequence template.

    You should copy your existing template JSON (the one you uploaded)
    into the project root and name it 'nina_template.json', or change the
    default path here.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_nina_sequence_from_blocks(
    template: dict,
    target_name: str,
    camera_cool_temp: float,
    blocks: List[Dict[str, Any]],
) -> dict:
    """
    Given a template sequence and a list of 'blocks', build a new
    NINA sequence JSON.

    blocks = [
      {
        "channel": "H",        # your short code
        "exposure_s": 300,
        "frames": 20,
      },
      ...
    ]
    """

    # Root containers
    root_items = template["Items"]["$values"]
    start_container = root_items[0]   # StartAreaContainer
    target_container = root_items[1]  # TargetAreaContainer
    # end_container = root_items[2]   # EndAreaContainer (we don't change it)

    # --- Start: camera cooling temp ---
    start_items = start_container["Items"]["$values"]
    if start_items and start_items[0]["$type"].startswith(
        "NINA.Sequencer.SequenceItem.Camera.CoolCamera"
    ):
        cool = start_items[0]
        cool["Temperature"] = float(camera_cool_temp)

    # --- Target area: build filter blocks based on remaining subs ---
    t_items = target_container["Items"]["$values"]
    if len(t_items) < 5:
        raise RuntimeError(
            "Unexpected template structure: target container does not have 5 items."
        )

    # Structure we discovered in your template:
    # 0: SetTracking
    # 1: Wait 3s
    # 2: SwitchFilter (Ha)
    # 3: Wait 3s
    # 4: TakeManyExposures (LoopCondition + TakeExposure)
    track_template = t_items[0]
    wait1_template = t_items[1]
    switch_template = t_items[2]
    wait2_template = t_items[3]
    many_template = t_items[4]

    new_t_items: list[dict] = []

    # Keep a single "Set Tracking" at the top
    new_t_items.append(track_template)

    # We only need to rewrite the ID for the TakeManyExposures root object,
    # because its 'LoopCondition' and 'TakeExposure' refer to this ID using $ref.
    orig_many_id = many_template.get("$id")

    def fix_many_ids(many_obj: dict, idx: int) -> None:
        """
        Give each cloned TakeManyExposures its own $id and fix the internal $ref.
        """
        if not orig_many_id:
            return

        new_id = f"{orig_many_id}_{idx+1}"

        def recur(o: Any) -> None:
            if isinstance(o, dict):
                if o.get("$id") == orig_many_id:
                    o["$id"] = new_id
                if o.get("$ref") == orig_many_id:
                    o["$ref"] = new_id
                for v in o.values():
                    recur(v)
            elif isinstance(o, list):
                for v in o:
                    recur(v)

        recur(many_obj)

    # For each remaining block, we create:
    # Wait -> SwitchFilter -> Wait -> TakeManyExposures
    
    # Get filter configuration (from active wheel or legacy fallback)
    filter_config = get_filter_config()
    
    for idx, block in enumerate(blocks):
        chan = block["channel"]
        exposure_s = float(block["exposure_s"])
        frames = int(block["frames"])

        if frames <= 0:
            continue

        cfg = filter_config.get(chan)
        if not cfg:
            # unknown channel, skip
            logger.warning(f"Unknown channel '{chan}' - skipping in NINA export")
            continue

        # Clone templates
        w1 = _deep_clone(wait1_template)
        sw = _deep_clone(switch_template)
        w2 = _deep_clone(wait2_template)
        mn = _deep_clone(many_template)

        # Patch filter info
        filt_info = sw["Filter"]
        filt_info["_name"] = cfg["nina_name"]
        filt_info["_position"] = cfg["position"]

        # Fix IDs & refs for this TakeManyExposures block
        fix_many_ids(mn, idx)

        # Patch exposure count + exposure time
        loop_cond = mn["Conditions"]["$values"][0]
        take_exp = mn["Items"]["$values"][0]
        loop_cond["Iterations"] = frames
        take_exp["ExposureTime"] = exposure_s

        # Append to new item list
        new_t_items.extend([w1, sw, w2, mn])

    target_container["Items"]["$values"] = new_t_items

    # Give the sequence a nice name
    template["Name"] = f"ArmillaryLab – {target_name}"

    return template


# ─────────────────────────────────────────────────────────────────────────────
# NINA V2 Advanced Sequence Builder  (v2.6.0)
# Uses nina_template_v2.json — proper DeepSkyObjectContainer + full session
# start workflow (CenterAndRotate, guiding, per-channel loops with dither).
# ─────────────────────────────────────────────────────────────────────────────

def ra_dec_to_nina_coords(ra_hours: float, dec_deg: float) -> dict:
    """Convert decimal RA (hours) + Dec (degrees) to NINA's component HMS/DMS dict."""
    ra_h = int(ra_hours)
    ra_rem = (ra_hours - ra_h) * 60.0
    ra_m = int(ra_rem)
    ra_s = (ra_rem - ra_m) * 60.0

    negative = dec_deg < 0
    dec_abs = abs(dec_deg)
    dec_d = int(dec_abs)
    dec_rem = (dec_abs - dec_d) * 60.0
    dec_m = int(dec_rem)
    dec_s = (dec_rem - dec_m) * 60.0

    return {
        "RAHours": ra_h,
        "RAMinutes": ra_m,
        "RASeconds": round(ra_s, 5),
        "NegativeDec": negative,
        "DecDegrees": dec_d,
        "DecMinutes": dec_m,
        "DecSeconds": round(dec_s, 5),
    }


def _collect_ids_in_subtree(obj: Any) -> set:
    """Return the set of all $id string values defined within a JSON subtree."""
    ids: set = set()
    if isinstance(obj, dict):
        if "$id" in obj:
            ids.add(str(obj["$id"]))
        for v in obj.values():
            ids.update(_collect_ids_in_subtree(v))
    elif isinstance(obj, list):
        for v in obj:
            ids.update(_collect_ids_in_subtree(v))
    return ids


def _apply_id_remap(obj: Any, id_map: dict) -> None:
    """
    In-place walk: replace $id / $ref string values found in id_map.
    External refs (IDs not in id_map) are left untouched.
    """
    if isinstance(obj, dict):
        if "$id" in obj and str(obj["$id"]) in id_map:
            obj["$id"] = id_map[str(obj["$id"])]
        if "$ref" in obj and str(obj["$ref"]) in id_map:
            obj["$ref"] = id_map[str(obj["$ref"])]
        for v in obj.values():
            _apply_id_remap(v, id_map)
    elif isinstance(obj, list):
        for v in obj:
            _apply_id_remap(v, id_map)


def _find_max_id(obj: Any) -> int:
    """Return the highest integer $id value found anywhere in a JSON tree."""
    max_val = 0
    if isinstance(obj, dict):
        if "$id" in obj:
            try:
                max_val = max(max_val, int(obj["$id"]))
            except (ValueError, TypeError):
                pass
        for v in obj.values():
            max_val = max(max_val, _find_max_id(v))
    elif isinstance(obj, list):
        for v in obj:
            max_val = max(max_val, _find_max_id(v))
    return max_val


def _resequence_subtree(subtree: Any, start_id: int):
    """
    Deep-clone *subtree*, reassign every $id defined within it to sequential
    integers starting at *start_id*, and update internal $ref references.
    External $refs (IDs not defined inside the subtree) are preserved as-is.

    Returns (new_subtree, next_available_id).
    """
    clone = _deep_clone(subtree)
    local_ids = _collect_ids_in_subtree(clone)
    sorted_ids = sorted(local_ids, key=lambda x: int(x) if x.isdigit() else 0)
    id_map = {}
    nxt = start_id
    for old in sorted_ids:
        id_map[old] = str(nxt)
        nxt += 1
    _apply_id_remap(clone, id_map)
    return clone, nxt


def build_nina_sequence_v2(
    target_name: str,
    ra_hours: float,
    dec_deg: float,
    position_angle: float,
    channels: List[Dict[str, Any]],
    cool_duration_min: float = 10.0,
    force_calibration: bool = False,
    dither_after: int = 3,
    window_end_local=None,
    container_name: Optional[str] = None,
    sequence_name: Optional[str] = None,
    use_exposure_offset: bool = False,
) -> dict:
    """
    Build a single NINA Advanced Sequence JSON using *nina_template_v2.json*.

    channels — list of dicts, each with:
      name        display/channel name (e.g. "Ha")
      nina_name   NINA filter name    (e.g. "Ha")
      position    filter wheel slot   (int)
      exposure_s  sub-exposure time   (float seconds)
      remaining   frames still to capture (int)
      captured    frames already logged   (int, used when use_exposure_offset=True)
      gain        sensor gain             (int)

    window_end_local — datetime with tzinfo; sets the TimeCondition stop time.
    use_exposure_offset — experimental: set TakeExposure.ExposureCount to
                          already-captured frames instead of 0.
    """
    if container_name is None:
        container_name = f"{target_name} Capture"
    if sequence_name is None:
        sequence_name = target_name

    seq = load_nina_template("nina_template_v2.json")

    # ── Root sequence name ────────────────────────────────────────────────────
    seq["Name"] = sequence_name

    # ── Start area: CoolCamera Duration ──────────────────────────────────────
    cool_camera = seq["Items"]["$values"][0]["Items"]["$values"][0]
    cool_camera["Duration"] = float(cool_duration_min)

    # ── Target area: locate DeepSkyObjectContainer ───────────────────────────
    target_area_items = seq["Items"]["$values"][1]["Items"]["$values"]
    # [0] = INIT (static), [1] = DeepSkyObjectContainer
    dso = target_area_items[1]

    # Container display name
    dso["Name"] = container_name

    # ── Target block (name, position angle, coordinates) ─────────────────────
    target_block = dso["Target"]
    target_block["TargetName"] = target_name
    target_block["PositionAngle"] = float(position_angle)
    coords = ra_dec_to_nina_coords(ra_hours, dec_deg)
    # Update fields in-place to preserve $id and $type
    target_block["InputCoordinates"].update(coords)

    # ── TimeCondition (session stop time) ────────────────────────────────────
    time_cond = dso["Conditions"]["$values"][0]
    if window_end_local is not None:
        time_cond["Hours"] = window_end_local.hour
        time_cond["Minutes"] = window_end_local.minute
        time_cond["Seconds"] = window_end_local.second
        time_cond["MinutesOffset"] = 0
    else:
        time_cond["Hours"] = 0
        time_cond["Minutes"] = 0
        time_cond["Seconds"] = 0
        time_cond["MinutesOffset"] = 0

    # ── Static DSO items ─────────────────────────────────────────────────────
    dso_items = dso["Items"]["$values"]
    # [0] SwitchFilter L  — static
    # [1] WaitForTimeSpan — static
    # [2] CenterAndRotate — update position angle + coordinates
    center_rotate = dso_items[2]
    center_rotate["PositionAngle"] = float(position_angle)
    center_rotate["Coordinates"].update(coords)
    # [3] SetTracking     — static
    # [4] StartGuiding    — ForceCalibration toggle
    dso_items[4]["ForceCalibration"] = bool(force_calibration)
    # [5] WaitForTimeSpan — static
    # [6] channel block template — to be replaced below
    channel_block_template = dso_items[6]

    # Verify expected type (fail early rather than produce a silently broken file)
    expected_type = "NINA.Sequencer.Container.SequentialContainer"
    if expected_type not in channel_block_template.get("$type", ""):
        raise RuntimeError(
            f"nina_template_v2.json: expected SequentialContainer at DSO Items[6], "
            f"got: {channel_block_template.get('$type', '?')}"
        )

    # ── Channel blocks ────────────────────────────────────────────────────────
    # IDs in the template go up to 77; start fresh clones from 78 onward.
    next_id = _find_max_id(seq) + 1
    dso_id = str(dso.get("$id", "18"))

    new_channel_blocks: list = []
    for ch in channels:
        if ch.get("remaining", 0) <= 0:
            continue

        block, next_id = _resequence_subtree(channel_block_template, next_id)

        # Ensure parent ref points to DSO container (survives resequencing
        # because dso_id is external to the channel block subtree)
        block["Parent"] = {"$ref": dso_id}

        # Channel container name
        block["Name"] = ch["name"]

        # LoopCondition
        loop_cond = block["Conditions"]["$values"][0]
        loop_cond["Iterations"] = int(ch["remaining"])
        loop_cond["CompletedIterations"] = 0

        # Capture items: [0] SwitchFilter, [1] Wait (settle), [2] TakeExposure
        items = block["Items"]["$values"]
        items[0]["Filter"]["_name"] = ch["nina_name"]
        items[0]["Filter"]["_position"] = int(ch["position"])
        items[2]["ExposureTime"] = float(ch["exposure_s"])
        items[2]["Gain"] = int(ch["gain"])
        items[2]["ExposureCount"] = (
            int(ch.get("captured", 0)) if use_exposure_offset else 0
        )

        # Dither trigger
        block["Triggers"]["$values"][0]["AfterExposures"] = int(dither_after)

        new_channel_blocks.append(block)

    if not new_channel_blocks:
        raise ValueError("No channels with remaining frames to export.")

    # Replace the single template channel block with our populated list
    dso["Items"]["$values"] = dso_items[:6] + new_channel_blocks

    return seq


def build_nina_sequences_v2(
    target_name: str,
    ra_hours: float,
    dec_deg: float,
    position_angle: float,
    channels: List[Dict[str, Any]],
    cool_duration_min: float = 10.0,
    force_calibration: bool = False,
    dither_after: int = 3,
    window_end_local=None,
    container_name: Optional[str] = None,
    sequence_name: Optional[str] = None,
    use_exposure_offset: bool = False,
    export_mode: str = "all",
) -> Any:
    """
    Dispatcher for V2 exports.

    export_mode:
      "all"    — all channels in a single JSON dict
      "single" — caller passes a channels list with exactly one entry;
                 returns a single JSON dict
      "zip"    — one JSON per channel; returns list of (filename, dict) tuples
    """
    if export_mode in ("all", "single"):
        return build_nina_sequence_v2(
            target_name=target_name,
            ra_hours=ra_hours,
            dec_deg=dec_deg,
            position_angle=position_angle,
            channels=channels,
            cool_duration_min=cool_duration_min,
            force_calibration=force_calibration,
            dither_after=dither_after,
            window_end_local=window_end_local,
            container_name=container_name,
            sequence_name=sequence_name,
            use_exposure_offset=use_exposure_offset,
        )

    # zip mode — one file per channel
    results = []
    for ch in channels:
        if ch.get("remaining", 0) <= 0:
            continue
        ch_seq_name = f"{sequence_name or target_name} \u2013 {ch['name']}"
        seq = build_nina_sequence_v2(
            target_name=target_name,
            ra_hours=ra_hours,
            dec_deg=dec_deg,
            position_angle=position_angle,
            channels=[ch],
            cool_duration_min=cool_duration_min,
            force_calibration=force_calibration,
            dither_after=dither_after,
            window_end_local=window_end_local,
            container_name=container_name or f"{target_name} Capture",
            sequence_name=ch_seq_name,
            use_exposure_offset=use_exposure_offset,
        )
        safe_target = target_name.replace(" ", "_")
        safe_ch = ch["name"].replace(" ", "_").replace("/", "-")
        filename = f"ArmillaryLab_{safe_target}_{safe_ch}.json"
        results.append((filename, seq))
    return results
