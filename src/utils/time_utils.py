from datetime import datetime, time, date
import pytz
from typing import Tuple

IST = pytz.timezone("Asia/Kolkata")

def get_now_ist() -> datetime:
    """Return current localized IST datetime."""
    return datetime.now(IST)

def is_market_open(now: datetime = None) -> bool:
    """Return True if current time is within Indian trading session (09:15 - 15:30 IST on weekdays)."""
    if now is None:
        now = get_now_ist()
    # Check weekday (0 = Monday, 4 = Friday)
    if now.weekday() >= 5:
        return False
    market_open = time(9, 15)
    market_close = time(15, 30)
    current_time = now.time()
    return market_open <= current_time <= market_close

def is_intraday_exit_time(now: datetime = None, exit_time_str: str = "15:15") -> bool:
    """Check if intraday square-off time has been reached."""
    if now is None:
        now = get_now_ist()
    h, m = map(int, exit_time_str.split(":"))
    cutoff = time(h, m)
    return now.time() >= cutoff

def time_to_expiry_in_years(expiry_date: date, current_time: datetime = None) -> float:
    """Calculate annual fraction to expiry (e.g. 3.5 days / 365)."""
    if current_time is None:
        current_time = get_now_ist()
    
    expiry_dt = IST.localize(datetime.combine(expiry_date, time(15, 30)))
    delta_seconds = (expiry_dt - current_time).total_seconds()
    if delta_seconds <= 0:
        return 0.0001
    return delta_seconds / (365.25 * 86400.0)
