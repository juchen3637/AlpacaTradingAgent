"""
Market hours utilities for validating trading hours and checking if the market is open.
"""

import datetime
import pytz
from typing import Tuple, Dict, Any

# US stock market holidays (simplified - in production, use a proper holidays library)
US_MARKET_HOLIDAYS_2024 = [
    "2024-01-01",  # New Year's Day
    "2024-01-15",  # Martin Luther King Jr. Day
    "2024-02-19",  # Presidents' Day
    "2024-03-29",  # Good Friday
    "2024-05-27",  # Memorial Day
    "2024-06-19",  # Juneteenth
    "2024-07-04",  # Independence Day
    "2024-09-02",  # Labor Day
    "2024-11-28",  # Thanksgiving Day
    "2024-12-25",  # Christmas Day
]

US_MARKET_HOLIDAYS_2025 = [
    "2025-01-01",  # New Year's Day
    "2025-01-20",  # Martin Luther King Jr. Day
    "2025-02-17",  # Presidents' Day
    "2025-04-18",  # Good Friday
    "2025-05-26",  # Memorial Day
    "2025-06-19",  # Juneteenth
    "2025-07-04",  # Independence Day
    "2025-09-01",  # Labor Day
    "2025-11-27",  # Thanksgiving Day
    "2025-12-25",  # Christmas Day
]

US_MARKET_HOLIDAYS_2026 = [
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # Martin Luther King Jr. Day
    "2026-02-16",  # Washington's Birthday
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth National Independence Day
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving Day
    "2026-12-25",  # Christmas Day
]

US_MARKET_HOLIDAYS_2027 = [
    "2027-01-01",  # New Year's Day
    "2027-01-18",  # Martin Luther King Jr. Day
    "2027-02-15",  # Washington's Birthday
    "2027-03-26",  # Good Friday
    "2027-05-31",  # Memorial Day
    "2027-06-18",  # Juneteenth National Independence Day (observed)
    "2027-07-05",  # Independence Day (observed)
    "2027-09-06",  # Labor Day
    "2027-11-25",  # Thanksgiving Day
    "2027-12-24",  # Christmas Day (observed)
]

ALL_HOLIDAYS = (
    US_MARKET_HOLIDAYS_2024
    + US_MARKET_HOLIDAYS_2025
    + US_MARKET_HOLIDAYS_2026
    + US_MARKET_HOLIDAYS_2027
)

# Absolute market bounds
MARKET_OPEN_HOUR = 9
MARKET_CLOSE_HOUR = 16


def validate_market_hours(hours_str: str) -> Tuple[bool, Tuple[int, int], str]:
    """
    Validate market hours range input string (e.g. "9,16").

    Returns:
        (is_valid, (start_hour, end_hour), error_message)
    """
    if not hours_str or not hours_str.strip():
        return False, (0, 0), "Please enter a start and end hour (e.g. 9,16)"

    parts = [p.strip() for p in hours_str.split(",") if p.strip()]

    if len(parts) != 2:
        return False, (0, 0), "Enter exactly two hours separated by a comma (e.g. 9,16)"

    try:
        start_hour = int(parts[0])
        end_hour = int(parts[1])
    except ValueError:
        return False, (0, 0), "Please enter valid hour numbers (e.g. 9,16)"

    if start_hour < MARKET_OPEN_HOUR or start_hour > MARKET_CLOSE_HOUR:
        return False, (0, 0), f"Start hour {start_hour} is outside market hours (9–16)"

    if end_hour < MARKET_OPEN_HOUR or end_hour > MARKET_CLOSE_HOUR:
        return False, (0, 0), f"End hour {end_hour} is outside market hours (9–16)"

    if start_hour >= end_hour:
        return False, (0, 0), "Start hour must be before end hour"

    return True, (start_hour, end_hour), ""


def _is_market_day(dt: datetime.datetime) -> Tuple[bool, str]:
    """Check if dt (Eastern) falls on a valid market day (weekday, non-holiday)."""
    if dt.weekday() >= 5:
        return False, "Market is closed on weekends"
    date_str = dt.strftime("%Y-%m-%d")
    if date_str in ALL_HOLIDAYS:
        return False, f"Market is closed for holiday on {date_str}"
    return True, "Market day"


def is_market_open(target_datetime: datetime.datetime = None) -> Tuple[bool, str]:
    """
    Check if the US stock market is open at the given datetime.

    Returns:
        (is_open, reason_if_closed)
    """
    eastern = pytz.timezone("US/Eastern")
    if target_datetime is None:
        target_datetime = datetime.datetime.now(tz=pytz.UTC).astimezone(eastern)
    elif target_datetime.tzinfo is None:
        target_datetime = eastern.localize(target_datetime)
    else:
        target_datetime = target_datetime.astimezone(eastern)

    is_day, reason = _is_market_day(target_datetime)
    if not is_day:
        return False, reason

    market_open = target_datetime.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = target_datetime.replace(hour=16, minute=0, second=0, microsecond=0)

    if target_datetime < market_open:
        return False, f"Market opens at 9:30 AM EST/EDT (currently {target_datetime.strftime('%I:%M %p %Z')})"
    if target_datetime > market_close:
        return False, f"Market closed at 4:00 PM EST/EDT (currently {target_datetime.strftime('%I:%M %p %Z')})"

    return True, "Market is open"


def get_next_run_datetime(
    start_hour: int,
    end_hour: int,
    from_datetime: datetime.datetime = None,
    immediate: bool = False,
) -> Tuple[datetime.datetime, bool]:
    """
    Calculate when the next analysis run should happen given a trading range.

    If immediate=True and current time is within [start_hour, end_hour] on a market day,
    returns (now, True) so the caller runs immediately.

    Otherwise returns (next_top_of_hour_within_range_on_next_valid_market_day, False).

    Returns:
        (next_dt, run_now)
        run_now=True means fire immediately without waiting.
    """
    eastern = pytz.timezone("US/Eastern")
    if from_datetime is None:
        now = datetime.datetime.now(tz=pytz.UTC).astimezone(eastern)
    elif from_datetime.tzinfo is None:
        now = eastern.localize(from_datetime)
    else:
        now = from_datetime.astimezone(eastern)

    if immediate:
        # Check if we're currently within the trading window on a market day
        is_day, _ = _is_market_day(now)
        if is_day and start_hour <= now.hour <= end_hour:
            return now, True

    # Find next top-of-hour within [start_hour, end_hour]
    # Start candidate: top of next hour
    candidate = now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)

    for _ in range(14):  # max 14 days forward
        is_day, _ = _is_market_day(candidate)
        if is_day and start_hour <= candidate.hour <= end_hour:
            return candidate, False
        # Advance: if past end_hour, jump to start_hour next day
        if candidate.hour > end_hour or not is_day:
            candidate = (candidate + datetime.timedelta(days=1)).replace(
                hour=start_hour, minute=0, second=0, microsecond=0
            )
        else:
            candidate += datetime.timedelta(hours=1)

    return candidate, False


def format_market_hours_info(start_hour: int, end_hour: int) -> Dict[str, Any]:
    """Format market hours range information for display."""
    def fmt(h):
        if h == 0:
            return "12:00 AM"
        if h < 12:
            return f"{h}:00 AM"
        if h == 12:
            return "12:00 PM"
        return f"{h - 12}:00 PM"

    next_dt, run_now = get_next_run_datetime(start_hour, end_hour, immediate=True)
    if run_now:
        next_str = "Immediately (within trading window)"
    else:
        next_str = next_dt.strftime("%A, %B %d at %I:%M %p %Z")

    return {
        "start_hour": start_hour,
        "end_hour": end_hour,
        "formatted_range": f"{fmt(start_hour)} – {fmt(end_hour)} EST/EDT",
        "next_run": next_str,
    }
