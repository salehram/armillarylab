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


def _capture_dict(capture) -> dict:
    return {
        "frame_type": capture.frame_type,
        "channel": capture.channel,
        "checkpoint": capture.checkpoint,
        "frame_count": capture.frame_count,
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

    summary: dict[str, Any] = {
        "darks": {
            "planned": config.get("darks", 0),
            "captured": _captured_total(capture_dicts, None, "dark"),
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

            if two_point and ratio >= 0.5 and not detail["mid_complete"]:
                suggested = max(mid_target - captured_mid, 0)
                if suggested > 0:
                    suggestions.append(
                        {
                            "channel": ch_name,
                            "frame_type": frame_type,
                            "checkpoint": "midpoint",
                            "suggested_count": suggested,
                            "captured_so_far": captured_mid,
                            "actions": ["log", "skip"],
                        }
                    )

            if lights_complete and not detail["end_complete"]:
                end_needed = max(total_per - captured_total, 0)
                if end_needed > 0:
                    suggestions.append(
                        {
                            "channel": ch_name,
                            "frame_type": frame_type,
                            "checkpoint": "end",
                            "suggested_count": end_needed,
                            "captured_so_far": captured_total,
                            "actions": ["log", "skip"],
                        }
                    )

    return suggestions


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


def format_suggestion_flash(suggestions: list[dict]) -> str | None:
    """Build a human-readable flash message from active suggestions."""
    if not suggestions:
        return None
    parts = []
    for s in suggestions[:3]:
        label = s["frame_type"].replace("_", " ")
        parts.append(
            f"{s['channel']}: capture {s['suggested_count']} {label} ({s['checkpoint']})"
        )
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
        label = f"Cal: {s['frame_type'].replace('_', ' ')} {s['checkpoint']}"
        badges.setdefault(ch, []).append(label)
    return badges
