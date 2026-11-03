import json
import os
import requests
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from src.utils.logger import log

class InstrumentManager:
    """
    Manages strike step calculations, option ticker generation,
    and Angel One instrument master caching/lookup.
    """
    MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    CACHE_FILE = "data/scrip_master.json"

    # Default strike step intervals
    STRIKE_STEPS = {
        "NIFTY": 50,
        "BANKNIFTY": 100,
        "SENSEX": 100,
        "FINNIFTY": 50,
        "RELIANCE": 20,
        "HDFCBANK": 10,
        "ICICIBANK": 10,
        "INFY": 20,
        "SBIN": 10,
        "TATAMOTORS": 10,
        "TCS": 50,
        "LT": 50,
        "BHARTIARTL": 20,
        "AXISBANK": 20,
        "MARUTI": 100,
        "KOTAKBANK": 20,
        "BAJFINANCE": 100,
        "M&M": 20,
        "SUNPHARMA": 20
    }

    def __init__(self, auto_download_master: bool = False):
        self.instruments_by_symbol: Dict[str, dict] = {}
        self.instruments_by_token: Dict[str, dict] = {}
        if auto_download_master:
            self.load_or_download_master()

    def get_strike_step(self, symbol: str) -> int:
        return self.STRIKE_STEPS.get(symbol.upper(), 50)

    def calculate_atm_strike(self, symbol: str, spot_price: float) -> float:
        """Find the closest valid strike to current spot price."""
        step = self.get_strike_step(symbol)
        return round(round(spot_price / step) * step, 1)

    def get_target_strike(
        self,
        symbol: str,
        spot_price: float,
        option_type: str, # "CE" or "PE"
        offset: int = 0   # 0 = ATM, 1 = 1 strike ITM, -1 = 1 strike OTM
    ) -> float:
        """
        Calculate ATM or near-ITM strike.
        For Call (CE): ITM is strike BELOW spot.
        For Put (PE): ITM is strike ABOVE spot.
        """
        atm = self.calculate_atm_strike(symbol, spot_price)
        step = self.get_strike_step(symbol)

        if option_type.upper() == "CE":
            # 1 strike ITM for Call is lower strike
            target = atm - (offset * step)
        else:
            # 1 strike ITM for Put is higher strike
            target = atm + (offset * step)

        return float(target)

    def get_next_expiry(self, symbol: str, current_date: date = None) -> date:
        """
        Determine the upcoming expiry date.
        NSE Weekly Expiry:
        - Nifty: Thursday (weekday 3)
        - Bank Nifty: Wednesday (weekday 2)
        - Sensex: Friday (weekday 4)
        - FinNifty: Tuesday (weekday 1)
        - Stocks: Monthly expiry (Last Thursday of the month)
        """
        if current_date is None:
            current_date = date.today()

        weekday = current_date.weekday()
        sym = symbol.upper()

        if sym == "FINNIFTY":
            target_weekday = 1 # Tuesday
        elif sym == "BANKNIFTY":
            target_weekday = 2 # Wednesday
        elif sym in ["NIFTY", "NIFTY 50"]:
            target_weekday = 3 # Thursday
        elif sym == "SENSEX":
            target_weekday = 4 # Friday
        else:
            # Monthly stock expiry: Last Thursday of month
            return self._get_last_thursday_of_month(current_date.year, current_date.month, current_date)

        days_ahead = (target_weekday - weekday) % 7
        if days_ahead == 0 and datetime.now().time() > datetime.strptime("15:30", "%H:%M").time():
            days_ahead = 7
        return current_date + timedelta(days=days_ahead)

    def _get_last_thursday_of_month(self, year: int, month: int, current_date: date) -> date:
        # Check last day of month
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        last_day = next_month - timedelta(days=1)
        
        # Walk back to Thursday (weekday 3)
        offset = (last_day.weekday() - 3) % 7
        last_thursday = last_day - timedelta(days=offset)
        
        # If this month's last Thursday has passed, get next month's
        if last_thursday < current_date:
            if month == 12:
                return self._get_last_thursday_of_month(year + 1, 1, current_date)
            else:
                return self._get_last_thursday_of_month(year, month + 1, current_date)
        return last_thursday

    def format_contract_symbol(
        self,
        symbol: str,
        expiry: date,
        strike: float,
        option_type: str
    ) -> str:
        """Format standard readable contract ticker (e.g., NIFTY26NOV24200CE)."""
        strike_str = str(int(strike)) if strike.is_integer() else str(strike)
        month_str = expiry.strftime("%b").upper()
        day_str = expiry.strftime("%d")
        year_str = expiry.strftime("%y")
        return f"{symbol.upper()}{day_str}{month_str}{strike_str}{option_type.upper()}"

    def load_or_download_master(self):
        """Cache Angel One Scrip Master JSON for resolving live token IDs."""
        os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
        if not os.path.exists(self.CACHE_FILE):
            log.info("Downloading Angel One scrip master JSON (one-time cache)...")
            try:
                resp = requests.get(self.MASTER_URL, timeout=30)
                if resp.status_code == 200:
                    with open(self.CACHE_FILE, "wb") as f:
                        f.write(resp.content)
                    log.info("Scrip master saved successfully.")
            except Exception as e:
                log.error(f"Failed to download scrip master: {e}")
                return

        try:
            with open(self.CACHE_FILE, "r") as f:
                data = json.load(f)
                for item in data:
                    sym = item.get("symbol", "")
                    tok = item.get("token", "")
                    self.instruments_by_symbol[sym] = item
                    self.instruments_by_token[tok] = item
            log.info(f"Loaded {len(self.instruments_by_symbol)} instruments into cache.")
        except Exception as e:
            log.error(f"Error parsing scrip master: {e}")
