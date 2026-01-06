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
    template["Name"] = f"AstroPlanner – {target_name}"

    return template
