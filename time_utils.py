"""
Time formatting and parsing utilities for the ArmillaryLab application.
Handles conversion between minutes, seconds, and H:M:S format.
"""

def format_hms(total_seconds):
    """Convert seconds to H:M:S format string."""
    if total_seconds is None:
        return "0:00:00"
    
    total_seconds = max(0, int(total_seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def format_hms_short(total_seconds):
    """Convert seconds to short H:M format (no seconds if zero)."""
    if total_seconds is None:
        return "0:00"
    
    total_seconds = max(0, int(total_seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if seconds == 0:
        return f"{hours}:{minutes:02d}"
    else:
        return f"{hours}:{minutes:02d}:{seconds:02d}"


def parse_hms(hms_string):
    """Parse H:M:S or H:M string to total seconds.
    
    Supports formats:
    - "1:30:45" -> 1h 30m 45s = 5445 seconds
    - "1:30" -> 1h 30m = 5400 seconds  
    - "90" -> 90 minutes = 5400 seconds
    - "1.5" -> 1.5 hours = 5400 seconds
    
    Returns:
        int: Total seconds, or None if parsing fails
    """
    if not hms_string:
        return None
        
    hms_string = str(hms_string).strip()
    
    # Try to parse as H:M:S or H:M format
    if ":" in hms_string:
        parts = hms_string.split(":")
        try:
            if len(parts) == 2:  # H:M
                hours, minutes = map(int, parts)
                return hours * 3600 + minutes * 60
            elif len(parts) == 3:  # H:M:S
                hours, minutes, seconds = map(int, parts)
                return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            return None
    
    # Try to parse as decimal number (hours or minutes)
    try:
        value = float(hms_string)
        # If the value is reasonable for hours (< 24), treat as hours
        if value <= 24:
            return int(value * 3600)
        else:
            # Otherwise treat as minutes
            return int(value * 60)
    except ValueError:
        return None


def minutes_to_hms(minutes):
    """Convert minutes to H:M:S format."""
    if minutes is None:
        return "0:00:00"
    return format_hms(minutes * 60)


def hms_to_minutes(hms_string):
    """Convert H:M:S string to minutes."""
    seconds = parse_hms(hms_string)
    if seconds is None:
        return None
    return seconds / 60.0


# Template filter registration (for Jinja2)
def register_time_filters(app):
    """Register time formatting filters with Flask app."""
    app.jinja_env.filters['format_hms'] = format_hms  # expects seconds
    app.jinja_env.filters['format_hms_from_minutes'] = minutes_to_hms  # expects minutes
    app.jinja_env.filters['hms_short'] = format_hms_short
    app.jinja_env.filters['minutes_to_hms'] = minutes_to_hms


# For testing
if __name__ == "__main__":
    # Test cases
    test_cases = [
        (5445, "1:30:45"),  # 1h 30m 45s
        (5400, "1:30:00"),  # 1h 30m
        (3600, "1:00:00"),  # 1h
        (1800, "0:30:00"),  # 30m
        (90, "0:01:30"),    # 1m 30s
    ]
    
    print("Testing format_hms:")
    for seconds, expected in test_cases:
        result = format_hms(seconds)
        print(f"{seconds}s -> {result} (expected: {expected}) {'✓' if result == expected else '✗'}")
    
    print("\nTesting parse_hms:")
    parse_cases = [
        ("1:30:45", 5445),
        ("1:30", 5400),
        ("90", 5400),  # 90 minutes
        ("1.5", 5400),  # 1.5 hours
    ]
    
    for hms_str, expected in parse_cases:
        result = parse_hms(hms_str)
        print(f"'{hms_str}' -> {result}s (expected: {expected}) {'✓' if result == expected else '✗'}")