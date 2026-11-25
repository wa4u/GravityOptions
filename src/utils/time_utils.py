from datetime import datetime, time, date
import pytz
from typing import Tuple

IST = pytz.timezone("Asia/Kolkata")

# Official NSE / BSE Equity & Derivatives Trading Holidays (YYYY-MM-DD -> Holiday Name)
NSE_HOLIDAYS = {
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-20": "Id-Ul-Fitr (Ramzan Eid)",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-27": "Bakri Id",
    "2026-06-25": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas",
}

def get_market_holiday_name(now: datetime = None) -> str:
    """Return holiday name if date is an NSE trading holiday, else empty string."""
    if now is None:
        now = get_now_ist()
    return NSE_HOLIDAYS.get(now.strftime("%Y-%m-%d"), "")

def get_now_ist() -> datetime:
    """Return current localized IST datetime."""
    return datetime.now(IST)

def is_market_open(now: datetime = None) -> bool:
    """Return True if current time is within Indian trading session (09:15 - 15:30 IST on non-holiday weekdays)."""
    if now is None:
        now = get_now_ist()
    # Check weekday (0 = Monday, 4 = Friday)
    if now.weekday() >= 5:
        return False
    if get_market_holiday_name(now):
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
