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

    # Known active weekly & monthly expiry dates for 2026
    ACTIVE_EXPIRIES_2026 = {
        "NIFTY": [
            date(2026, 11, 9),
            date(2026, 11, 17),
            date(2026, 11, 23),
            date(2026, 12, 1),
            date(2026, 12, 8),
            date(2026, 12, 29),
            date(2027, 1, 25)
        ],
        "BANKNIFTY": [
            date(2026, 11, 11),
            date(2026, 11, 25),
            date(2026, 12, 30)
        ],
        "SENSEX": [
            date(2026, 11, 6),
            date(2026, 11, 13),
            date(2026, 11, 20),
            date(2026, 11, 27)
        ]
    }

    def get_next_expiry(self, symbol: str, current_date: date = None) -> date:
        """
        Determine the upcoming active expiry date matching the live exchange calendar.
        """
        if current_date is None:
            current_date = date.today()

        sym = symbol.upper()
        # Check against exchange calendar
        if sym in self.ACTIVE_EXPIRIES_2026:
            for exp in self.ACTIVE_EXPIRIES_2026[sym]:
                if exp >= current_date:
                    return exp

        # Fallback monthly stock expiry: Last Thursday of month
        return self._get_last_thursday_of_month(current_date.year, current_date.month, current_date)

    def format_contract_symbol(
        self,
        symbol: str,
        expiry: date,
        strike: float,
        option_type: str
    ) -> str:
        """Format contract ticker matching Angel One (e.g. NIFTY09NOV2623900CE)."""
        strike_str = str(int(strike)) if int(strike) == strike else str(strike)
        month_str = expiry.strftime("%b").upper()
        day_str = expiry.strftime("%d")
        year_str = expiry.strftime("%y")
        return f"{symbol.upper()}{day_str}{month_str}{year_str}{strike_str}{option_type.upper()}"

    def lookup_symbol(self, symbol: str) -> Optional[dict]:
        """Look up instrument details from Angel One scrip master."""
        if not self.instruments_by_symbol:
            self.load_or_download_master()
        return self.instruments_by_symbol.get(symbol.upper().strip())

    def find_option_contract(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        current_date: date = None
    ) -> Optional[dict]:
        """
        Dynamically find the nearest active exchange option contract
        for indices (OPTIDX) or stocks (OPTSTK) directly from Angel One master scrip.
        """
        if not self.instruments_by_symbol:
            self.load_or_download_master()

        if current_date is None:
            current_date = date.today()

        sym_upper = symbol.upper().strip()
        opt_upper = option_type.upper().strip()
        target_strike_val = round(float(strike) * 100, 2)

        candidates = []
        for sym, item in self.instruments_by_symbol.items():
            if (
                item.get("name") == sym_upper
                and item.get("exch_seg") in ["NFO", "BFO"]
                and item.get("instrumenttype") in ["OPTIDX", "OPTSTK"]
                and sym.endswith(opt_upper)
            ):
                try:
                    item_strike = round(float(item.get("strike", 0)), 2)
                    if abs(item_strike - target_strike_val) < 1.0:
                        exp_str = item.get("expiry", "")
                        exp_date = datetime.strptime(exp_str, "%d%b%Y").date()
                        if exp_date >= current_date:
                            candidates.append((exp_date, item))
                except Exception:
                    continue

        if candidates:
            # Sort chronologically by expiry date to pick the nearest active expiry
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]

        return None

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
