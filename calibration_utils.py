"""Calibration frame tracking and two-point flat/dark-flat suggestion logic."""

from __future__ import annotations

from math import ceil, floor
from typing import Any


def channel_light_frames(channel: dict, progress_seconds: dict) -> tuple[int, int, float]:
    """Return planned frames, done frames, and progress ratio for a light channel."""
    name = channel.get("name", "")
    planned_sec = (channel.get("planned_minutes") or 0) * 60
    sub_exp = channel.get("sub_exposure_seconds") or 300
    if sub_exp <= 0:
        sub_exp = 300
    planned_frames = ceil(planned_sec / sub_exp) if planned_sec > 0 else 0
    done_sec = progress_seconds.get(name, 0)
    done_frames = floor(done_sec / sub_exp) if sub_exp > 0 else 0
    ratio = done_frames / planned_frames if planned_frames > 0 else 0.0
    return planned_frames, done_frames, ratio


def plan_unique_sub_exposures(plan_data: dict | None) -> list[float]:
    """Distinct light sub-exposure durations from the capture plan."""
    if not plan_data or not plan_data.get("channels"):
        return []
    seen: set[float] = set()
    out: list[float] = []
    for ch in plan_data["channels"]:
        sub = ch.get("sub_exposure_seconds") or 300
        if sub <= 0:
            sub = 300
        sub_f = float(sub)
        if sub_f not in seen:
            seen.add(sub_f)
            out.append(sub_f)
    return sorted(out)


def _sub_exposure_matches(capture_sub: float | None, target_sub: float, unique_exposures: list[float]) -> bool:
    """True if a capture counts toward a plan exposure bucket."""
    if capture_sub is None:
        return len(unique_exposures) == 1 and abs(unique_exposures[0] - target_sub) < 0.01
    return abs(float(capture_sub) - float(target_sub)) < 0.01


def _captured_darks_for_exposure(
    captures: list[dict], sub_exposure_seconds: float, unique_exposures: list[float]
) -> int:
    total = 0
    for c in captures:
        if c["frame_type"] != "dark":
            continue
        if _sub_exposure_matches(c.get("sub_exposure_seconds"), sub_exposure_seconds, unique_exposures):
            total += c.get("frame_count", 0)
    return total


def _capture_dict(capture) -> dict:
    return {
        "frame_type": capture.frame_type,
        "channel": capture.channel,
        "checkpoint": capture.checkpoint,
        "frame_count": capture.frame_count,
        "sub_exposure_seconds": getattr(capture, "sub_exposure_seconds", None),
    }


def _skip_dict(skip) -> dict:
    return {
        "channel": skip.channel,
        "frame_type": skip.frame_type,
        "checkpoint": skip.checkpoint,
    }


def _is_skipped(skips: list[dict], channel: str, frame_type: str, checkpoint: str) -> bool:
    return any(
        s["channel"] == channel
        and s["frame_type"] == frame_type
        and s["checkpoint"] == checkpoint
        for s in skips
    )


def _captured_at_checkpoint(
    captures: list[dict], channel: str, frame_type: str, checkpoint: str
) -> int:
    total = 0
    for c in captures:
        if c["frame_type"] != frame_type or c.get("channel") != channel:
            continue
        if c.get("checkpoint") == checkpoint:
            total += c.get("frame_count", 0)
    return total


def _captured_total(captures: list[dict], channel: str | None, frame_type: str) -> int:
    total = 0
    for c in captures:
        if c["frame_type"] != frame_type:
            continue
        if channel is not None and c.get("channel") != channel:
            continue
        total += c.get("frame_count", 0)
    return total


def _channel_checkpoint_detail(
    *,
    frame_type: str,
    channel: str,
    total_per_channel: int,
    two_point: bool,
    captures: list[dict],
    skips: list[dict],
) -> dict:
    captured_total = _captured_total(captures, channel, frame_type)
    mid_target = total_per_channel // 2 if two_point else 0
    captured_mid = _captured_at_checkpoint(captures, channel, frame_type, "midpoint")
    captured_end = _captured_at_checkpoint(captures, channel, frame_type, "end")
    mid_skipped = _is_skipped(skips, channel, frame_type, "midpoint")
    end_skipped = _is_skipped(skips, channel, frame_type, "end")

    mid_complete = (
        not two_point
        or mid_skipped
        or mid_target <= 0
        or captured_mid >= mid_target
        or captured_total >= mid_target  # manual / bulk logs count toward midpoint
        or captured_total >= total_per_channel
        or total_per_channel <= 0
    )
    end_complete = (
        end_skipped
        or total_per_channel <= 0
        or captured_total >= total_per_channel
    )

    return {
        "planned": total_per_channel,
        "captured": captured_total,
        "mid_target": mid_target,
        "captured_mid": captured_mid,
        "captured_end": captured_end,
        "mid_skipped": mid_skipped,
        "end_skipped": end_skipped,
        "mid_complete": mid_complete,
        "end_complete": end_complete,
    }


def get_calibration_status(
    config: dict,
    plan_data: dict | None,
    progress_seconds: dict,
    captures,
    skips,
) -> dict:
    """Build summary dict for UI and API."""
    capture_dicts = [_capture_dict(c) for c in captures]
    skip_dicts = [_skip_dict(s) for s in skips]
    darks_per = config.get("darks", 0)
    unique_exposures = plan_unique_sub_exposures(plan_data)
    dark_exposure_rows = [
        {
            "sub_exposure_seconds": sub,
            "planned": darks_per,
            "captured": _captured_darks_for_exposure(capture_dicts, sub, unique_exposures),
        }
        for sub in unique_exposures
    ]
    darks_captured_total = sum(row["captured"] for row in dark_exposure_rows)

    summary: dict[str, Any] = {
        "darks": {
            "planned_per_exposure": darks_per,
            "exposures": dark_exposure_rows,
            "captured": darks_captured_total,
            "planned": darks_per * len(unique_exposures) if unique_exposures else darks_per,
        },
        "bias": {
            "planned": config.get("bias", 0),
            "captured": _captured_total(capture_dicts, None, "bias"),
        },
        "channels": {},
    }

    if not plan_data or not plan_data.get("channels"):
        return summary

    flats_per = config.get("flats_per_channel", 0)
    dark_flats_per = config.get("dark_flats_per_channel", 0)
    two_point = config.get("two_point", True)

    for ch in plan_data["channels"]:
        ch_name = ch.get("name")
        if not ch_name:
            continue
        planned_frames, done_frames, ratio = channel_light_frames(ch, progress_seconds)
        summary["channels"][ch_name] = {
            "light_planned_frames": planned_frames,
            "light_done_frames": done_frames,
            "light_ratio": ratio,
            "lights_complete": planned_frames > 0 and done_frames >= planned_frames,
            "flat": _channel_checkpoint_detail(
                frame_type="flat",
                channel=ch_name,
                total_per_channel=flats_per,
                two_point=two_point,
                captures=capture_dicts,
                skips=skip_dicts,
            ),
            "dark_flat": _channel_checkpoint_detail(
                frame_type="dark_flat",
                channel=ch_name,
                total_per_channel=dark_flats_per,
                two_point=two_point,
                captures=capture_dicts,
                skips=skip_dicts,
            ),
        }

    return summary


def get_calibration_suggestions(
    config: dict,
    plan_data: dict | None,
    progress_seconds: dict,
    captures,
    skips,
) -> list[dict]:
    """Return actionable calibration suggestions for flats and dark flats."""
    if not config.get("enabled"):
        return []

    status = get_calibration_status(config, plan_data, progress_seconds, captures, skips)
    suggestions: list[dict] = []
    two_point = config.get("two_point", True)

    for ch_name, ch_status in status.get("channels", {}).items():
        ratio = ch_status["light_ratio"]
        lights_complete = ch_status["lights_complete"]

        for frame_type in ("flat", "dark_flat"):
            total_per = config.get(
                "flats_per_channel" if frame_type == "flat" else "dark_flats_per_channel", 0
            )
            if total_per <= 0:
                continue

            detail = ch_status[frame_type]

            mid_target = detail["mid_target"]
            captured_mid = detail["captured_mid"]
            captured_total = detail["captured"]
            remaining_total = max(total_per - captured_total, 0)

            # Midpoint only while lights are still in progress — once complete, end covers all remainder.
            if two_point and ratio >= 0.5 and not detail["mid_complete"] and not lights_complete:
                suggested = max(mid_target - captured_mid, 0)
                if suggested > 0:
                    suggestions.append(
                        _build_suggestion(
                            channel=ch_name,
                            frame_type=frame_type,
                            checkpoint="midpoint",
                            suggested_count=suggested,
                            planned_total=total_per,
                            captured_total=captured_total,
                            remaining_total=remaining_total,
                        )
                    )

            if lights_complete and not detail["end_complete"]:
                end_needed = remaining_total
                if end_needed > 0:
                    midpoint_missed = (
                        two_point
                        and not detail["mid_complete"]
                        and not detail["mid_skipped"]
                    )
                    suggestions.append(
                        _build_suggestion(
                            channel=ch_name,
                            frame_type=frame_type,
                            checkpoint="end",
                            suggested_count=end_needed,
                            planned_total=total_per,
                            captured_total=captured_total,
                            remaining_total=end_needed,
                            midpoint_missed=midpoint_missed,
                        )
                    )

    return suggestions


def _build_suggestion(
    *,
    channel: str,
    frame_type: str,
    checkpoint: str,
    suggested_count: int,
    planned_total: int,
    captured_total: int,
    remaining_total: int,
    midpoint_missed: bool = False,
) -> dict:
    """Build a suggestion dict with display fields for UI and API."""
    frame_label = frame_type.replace("_", " ")
    if checkpoint == "midpoint":
        title = f"Log {suggested_count} {frame_label} at midpoint"
        detail = (
            f"First half of your {planned_total}-frame plan for {channel} "
            f"({captured_total} captured so far)"
        )
    else:
        title = f"Log {suggested_count} {frame_label} at end"
        if midpoint_missed and captured_total == 0:
            detail = (
                f"Full {planned_total}-frame set still needed for {channel} "
                f"(midpoint was not captured)"
            )
        elif captured_total > 0:
            detail = (
                f"{remaining_total} remaining of {planned_total} planned for {channel} "
                f"({captured_total} captured so far)"
            )
        else:
            detail = (
                f"{remaining_total} remaining of {planned_total} planned for {channel}"
            )

    return {
        "channel": channel,
        "frame_type": frame_type,
        "checkpoint": checkpoint,
        "suggested_count": suggested_count,
        "planned_total": planned_total,
        "captured_total": captured_total,
        "remaining_total": remaining_total,
        "midpoint_missed": midpoint_missed,
        "title": title,
        "detail": detail,
        "actions": ["log", "skip"],
    }


def get_calibration_payload(
    config: dict,
    plan_data: dict | None,
    progress_seconds: dict,
    captures,
    skips,
) -> dict:
    """Combined status + suggestions for templates and JSON API."""
    summary = get_calibration_status(config, plan_data, progress_seconds, captures, skips)
    suggestions = get_calibration_suggestions(
        config, plan_data, progress_seconds, captures, skips
    )
    return {"summary": summary, "suggestions": suggestions}


def aggregate_calibration_for_export(captures) -> dict:
    """Sum captured calibration frames for AstroBin export prefill."""
    totals = {"darks": 0, "flats": 0, "flat_darks": 0, "bias": 0}
    for c in captures:
        if c.frame_type == "dark":
            totals["darks"] += c.frame_count
        elif c.frame_type == "flat":
            totals["flats"] += c.frame_count
        elif c.frame_type == "dark_flat":
            totals["flat_darks"] += c.frame_count
        elif c.frame_type == "bias":
            totals["bias"] += c.frame_count
    return totals


def resolve_astrobin_calibration_columns(form, captures, use_tracked: bool = True) -> dict[str, str]:
    """Resolve uniform AstroBin calibration columns (legacy: same value on every row)."""
    tracked = aggregate_calibration_for_export(captures) if captures else {
        "darks": 0,
        "flats": 0,
        "flat_darks": 0,
        "bias": 0,
    }
    mapping = (
        ("darks", "darks"),
        ("flats", "flats"),
        ("flat_darks", "flat_darks"),
        ("bias", "bias"),
    )
    resolved: dict[str, str] = {}
    for form_key, track_key in mapping:
        raw = (form.get(form_key) or "").strip()
        if raw != "":
            resolved[form_key] = raw
        elif use_tracked and tracked.get(track_key, 0) > 0:
            resolved[form_key] = str(tracked[track_key])
        else:
            resolved[form_key] = ""
    return resolved


def _default_sub_exposure_for_filter(plan_data: dict | None, base_filter: str) -> float:
    if plan_data and plan_data.get("channels"):
        for ch in plan_data["channels"]:
            ch_name = (ch.get("nina_filter") or "").strip() or ch.get("name", "")
            if ch_name == base_filter or ch.get("name") == base_filter:
                sub = ch.get("sub_exposure_seconds") or 300
                return float(sub if sub > 0 else 300)
    return 300.0


def build_astrobin_export_rows(
    sessions,
    captures,
    filter_name_map: dict[str, str],
    plan_data: dict | None = None,
) -> list[dict]:
    """
    Build AstroBin CSV rows with calibration allocated per session.

    Matching rules (same as the in-app imaging log):
    - Darks: same date + sub-exposure matches light duration
    - Flats / dark flats: same date + channel matches filter
    - Bias: same date, applied to the first light row of that date
    - Orphan calibration (no matching light row): row with number=0
    """
    from collections import defaultdict

    RowKey = tuple[str, str, float]  # date, base_filter, duration

    def base_filter(channel: str) -> str:
        return filter_name_map.get(channel, channel)

    rows: dict[RowKey, dict] = {}

    for session in sessions:
        bf = base_filter(session.channel)
        key: RowKey = (session.date.strftime("%Y-%m-%d"), bf, float(session.sub_exposure_seconds))
        if key not in rows:
            rows[key] = {
                "date": key[0],
                "filter_name": bf,
                "number": 0,
                "duration": key[2],
                "darks": 0,
                "flats": 0,
                "flat_darks": 0,
                "bias": 0,
            }
        rows[key]["number"] += session.sub_count

    if not captures:
        return sorted(rows.values(), key=lambda r: (r["date"], r["filter_name"], r["duration"]))

    bias_by_date: dict[str, int] = defaultdict(int)
    for capture in captures:
        if capture.frame_type == "bias":
            bias_by_date[capture.date.strftime("%Y-%m-%d")] += capture.frame_count

    def find_row(date_str: str, bf: str, duration: float | None = None) -> RowKey | None:
        if duration is not None:
            key: RowKey = (date_str, bf, float(duration))
            return key if key in rows else None
        matches = [k for k in rows if k[0] == date_str and k[1] == bf]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return sorted(matches, key=lambda k: k[2])[0]
        return None

    def ensure_row(date_str: str, bf: str, duration: float) -> RowKey:
        key: RowKey = (date_str, bf, float(duration))
        if key not in rows:
            rows[key] = {
                "date": date_str,
                "filter_name": bf,
                "number": 0,
                "duration": float(duration),
                "darks": 0,
                "flats": 0,
                "flat_darks": 0,
                "bias": 0,
            }
        return key

    for capture in captures:
        date_str = capture.date.strftime("%Y-%m-%d")
        count = capture.frame_count
        ft = capture.frame_type

        if ft == "dark":
            sub = getattr(capture, "sub_exposure_seconds", None)
            if sub is None:
                continue
            matches = [k for k in rows if k[0] == date_str and abs(k[2] - float(sub)) < 0.01]
            if len(matches) == 1:
                key = matches[0]
            elif matches:
                key = sorted(matches, key=lambda k: k[1])[0]
            else:
                bf = (plan_data or {}).get("dominant_channel") or "H"
                key = ensure_row(date_str, bf, float(sub))
            rows[key]["darks"] += count

        elif ft in ("flat", "dark_flat"):
            ch = (capture.channel or "").strip().upper()
            if not ch:
                continue
            bf = base_filter(ch)
            col = "flats" if ft == "flat" else "flat_darks"
            key = find_row(date_str, bf)
            if key is None:
                dur = _default_sub_exposure_for_filter(plan_data, bf)
                key = ensure_row(date_str, bf, dur)
            rows[key][col] += count

    for date_str, bias_count in bias_by_date.items():
        day_keys = sorted([k for k in rows if k[0] == date_str], key=lambda k: (k[1], k[2]))
        if day_keys:
            rows[day_keys[0]]["bias"] += bias_count

    return sorted(rows.values(), key=lambda r: (r["date"], r["filter_name"], r["duration"]))


def _calibration_log_entry(capture) -> dict:
    label = capture.frame_type.replace("_", " ")
    sub = getattr(capture, "sub_exposure_seconds", None)
    if capture.frame_type == "dark" and sub:
        label = f"dark {int(sub) if sub == int(sub) else sub}s"
    return {
        "kind": "calibration",
        "id": capture.id,
        "frame_type": capture.frame_type,
        "frame_label": label,
        "channel": capture.channel,
        "frame_count": capture.frame_count,
        "checkpoint": capture.checkpoint,
        "sub_exposure_seconds": sub,
        "notes": capture.notes,
    }


def _light_log_entry(session) -> dict:
    return {
        "kind": "light",
        "id": session.id,
        "channel": session.channel,
        "sub_count": session.sub_count,
        "sub_exposure_seconds": session.sub_exposure_seconds,
        "notes": session.notes,
        "minutes": (session.sub_count * session.sub_exposure_seconds) / 60,
    }


def build_target_imaging_log_days(sessions, captures) -> list[tuple]:
    """Merge light sessions and calibration captures by date for one target."""
    from collections import defaultdict

    by_date: dict = defaultdict(list)
    for session in sessions:
        by_date[session.date].append(_light_log_entry(session))
    for capture in captures:
        by_date[capture.date].append(_calibration_log_entry(capture))

    days = []
    for day in sorted(by_date.keys(), reverse=True):
        entries = sorted(
            by_date[day],
            key=lambda e: (
                0 if e["kind"] == "light" else 1,
                e.get("channel") or "",
                e.get("frame_type") or "",
            ),
        )
        days.append((day, entries))
    return days


def build_global_imaging_log_days(sessions, captures) -> list[tuple]:
    """Merge cross-target light sessions and calibration captures by date."""
    from collections import defaultdict

    by_date: dict = defaultdict(lambda: defaultdict(list))

    for session in sessions:
        by_date[session.date][session.target_id].append({
            "target": session.target,
            **_light_log_entry(session),
        })
    for capture in captures:
        by_date[capture.date][capture.target_id].append({
            "target": capture.target,
            **_calibration_log_entry(capture),
        })

    days = []
    for day in sorted(by_date.keys(), reverse=True):
        target_groups = []
        for target_id in sorted(by_date[day].keys(), key=lambda tid: by_date[day][tid][0]["target"].name):
            entries = sorted(
                by_date[day][target_id],
                key=lambda e: (
                    0 if e["kind"] == "light" else 1,
                    e.get("channel") or "",
                    e.get("frame_type") or "",
                ),
            )
            target_groups.append({
                "target": entries[0]["target"],
                "entries": entries,
            })
        days.append((day, target_groups))
    return days


def calibration_log_stats(captures) -> dict:
    """Summary stats for calibration captures in log views."""
    totals = aggregate_calibration_for_export(captures)
    return {
        "capture_count": len(captures),
        "imaging_days": len({c.date for c in captures}) if captures else 0,
        "total_frames": sum(totals.values()),
        "totals": totals,
    }


def format_suggestion_flash(suggestions: list[dict]) -> str | None:
    """Build a human-readable flash message from active suggestions."""
    if not suggestions:
        return None
    parts = []
    for s in suggestions[:3]:
        parts.append(f"{s['channel']}: {s['title']} ({s['captured_total']}/{s['planned_total']})")
    msg = "; ".join(parts)
    if len(suggestions) > 3:
        msg += f" (+{len(suggestions) - 3} more)"
    return msg


def channel_calibration_badges(
    config: dict,
    plan_data: dict | None,
    progress_seconds: dict,
    captures,
    skips,
) -> dict[str, list[str]]:
    """Map channel name -> list of badge labels for plan table."""
    badges: dict[str, list[str]] = {}
    if not config.get("enabled"):
        return badges

    suggestions = get_calibration_suggestions(
        config, plan_data, progress_seconds, captures, skips
    )
    for s in suggestions:
        ch = s["channel"]
        label = (
            f"Cal: {s['frame_type'].replace('_', ' ')} {s['checkpoint']} "
            f"({s['captured_total']}/{s['planned_total']})"
        )
        badges.setdefault(ch, []).append(label)
    return badges
