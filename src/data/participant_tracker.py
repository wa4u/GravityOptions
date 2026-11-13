"""
Participant-wise Open Interest and Institutional Positioning Tracker for NSE Equity Derivatives.
Inspired by Mr. Chartist (Option Hub) methodology.

Source: NSE publishes fao_participant_oi_DDMMYYYY.csv every trading day after market close.
Tracks:
- FII (Foreign Institutional Investors)
- DII (Domestic Institutional Investors)
- Pro (Proprietary Trading Desks)
- Client (Retail Traders)

Metrics:
- Index Futures Long %: Long / (Long + Short)
- Net Index Direction: (Fut Long - Fut Short) + (Call Long - Call Short) - (Put Long - Put Short)
- Macro Institutional Bias: BULLISH, BEARISH, or NEUTRAL
"""

import os
import json
import csv
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, Tuple
from src.utils.logger import log
from src.utils.time_utils import get_now_ist

CACHE_FILE = "data/participant_oi_cache.json"

class ParticipantTracker:
    def __init__(self, cache_file: str = CACHE_FILE):
        self.cache_file = cache_file
        self.data: Dict[str, Any] = {}
        self._load_cache()

    def _load_cache(self):
        """Loads cached participant data if available."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                log.warning(f"[ParticipantTracker] Could not load cache: {e}")

    def _save_cache(self):
        """Saves participant data to cache file."""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            log.warning(f"[ParticipantTracker] Could not save cache: {e}")

    def get_latest_positioning(self, max_lookback_days: int = 7) -> Optional[Dict[str, Any]]:
        """
        Fetches the latest participant OI report from NSE archives.
        Walks backwards from today over business days until a valid file is found.
        """
        today = get_now_ist().date()
        
        # Check if cache is fresh (updated for today or yesterday's trading close)
        cached_date = self.data.get("report_date")
        if cached_date:
            try:
                c_dt = datetime.strptime(cached_date, "%Y-%m-%d").date()
                # If cached within last 2 days and weekday, consider it usable unless after 18:30 IST today
                now_ist = get_now_ist()
                if c_dt == today:
                    return self.data
                elif (today - c_dt).days == 1 and now_ist.hour < 18:
                    return self.data
            except Exception:
                pass

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        # Try downloading starting from yesterday (or today if after 18:30 IST)
        start_date = today if get_now_ist().hour >= 19 else today - timedelta(days=1)
        
        for i in range(max_lookback_days):
            check_date = start_date - timedelta(days=i)
            if check_date.weekday() >= 5: # Saturday or Sunday
                continue

            d_str = check_date.strftime("%d%m%Y")
            url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{d_str}.csv"
            
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        content = resp.read().decode("utf-8", errors="ignore")
                        parsed = self._parse_nse_csv(content, check_date.strftime("%Y-%m-%d"))
                        if parsed:
                            self.data = parsed
                            self._save_cache()
                            log.info(f"🏛️ [ParticipantTracker] Successfully loaded NSE Participant OI for {check_date}")
                            return self.data
            except Exception:
                # File not published yet for this date, try previous day
                continue

        # If network failed, fall back to cached data if exists
        if self.data:
            log.info("🏛️ [ParticipantTracker] Using offline cached participant data")
            return self.data

        return None

    def _parse_nse_csv(self, csv_text: str, report_date: str) -> Optional[Dict[str, Any]]:
        """Parses the raw CSV content from NSE into structured participant metrics."""
        lines = [line.strip() for line in csv_text.splitlines() if line.strip()]
        if len(lines) < 3:
            return None

        # Find header line (starts with Client Type)
        header_idx = -1
        for idx, line in enumerate(lines):
            if "Client Type" in line:
                header_idx = idx
                break

        if header_idx == -1:
            return None

        reader = csv.DictReader(lines[header_idx:])
        participants: Dict[str, Dict[str, Any]] = {}

        for row in reader:
            client_type = row.get("Client Type", "").strip()
            if not client_type or client_type.startswith("Total"):
                continue

            def parse_val(col_name: str) -> int:
                for key in row:
                    if col_name.lower() in key.lower():
                        try:
                            return int(float(row[key].replace(",", "").strip()))
                        except Exception:
                            return 0
                return 0

            fut_idx_long = parse_val("Future Index Long")
            fut_idx_short = parse_val("Future Index Short")
            opt_idx_call_long = parse_val("Option Index Call Long")
            opt_idx_call_short = parse_val("Option Index Call Short")
            opt_idx_put_long = parse_val("Option Index Put Long")
            opt_idx_put_short = parse_val("Option Index Put Short")

            total_fut = fut_idx_long + fut_idx_short
            long_pct = (fut_idx_long / total_fut * 100.0) if total_fut > 0 else 50.0

            # Net index direction: (Fut Long - Fut Short) + (Call Long - Call Short) - (Put Long - Put Short)
            net_futures = fut_idx_long - fut_idx_short
            net_calls = opt_idx_call_long - opt_idx_call_short
            net_puts = opt_idx_put_long - opt_idx_put_short
            net_direction = net_futures + net_calls - net_puts

            participants[client_type.upper()] = {
                "client_type": client_type,
                "fut_idx_long": fut_idx_long,
                "fut_idx_short": fut_idx_short,
                "fut_long_pct": round(long_pct, 1),
                "net_futures": net_futures,
                "net_calls": net_calls,
                "net_puts": net_puts,
                "net_direction": net_direction
            }

        # Calculate macro institutional bias
        fii = participants.get("FII")
        client = participants.get("CLIENT")

        bias = "NEUTRAL"
        bias_reason = "Balanced FII positioning"

        if fii:
            fii_long_pct = fii["fut_long_pct"]
            fii_dir = fii["net_direction"]

            if fii_long_pct < 25.0:
                # Extreme FII oversold / short trap -> High potential for violent CE short-covering
                bias = "OVERSOLD_BOUNCE"
                bias_reason = f"FII Index Futures Extreme Short ({fii_long_pct:.1f}% Long, Net: {fii_dir:+,d}) -> Prone to Short Squeeze"
            elif fii_long_pct > 75.0:
                bias = "OVERBOUGHT_CORRECTION"
                bias_reason = f"FII Index Futures Crowded Long ({fii_long_pct:.1f}% Long, Net: {fii_dir:+,d}) -> Prone to Long Unwinding"
            elif fii_dir < -200000:
                bias = "BEARISH"
                bias_reason = f"FII Heavy Net Short ({fii_dir:+,d} contracts, {fii_long_pct:.1f}% Fut Long)"
            elif fii_dir > 200000:
                bias = "BULLISH"
                bias_reason = f"FII Heavy Net Long ({fii_dir:+,d} contracts, {fii_long_pct:.1f}% Fut Long)"
            elif fii_long_pct < 45.0:
                bias = "MILD_BEARISH"
                bias_reason = f"FII Moderate Short Bias ({fii_long_pct:.1f}% Fut Long)"
            elif fii_long_pct > 55.0:
                bias = "MILD_BULLISH"
                bias_reason = f"FII Moderate Long Bias ({fii_long_pct:.1f}% Fut Long)"

        return {
            "report_date": report_date,
            "bias": bias,
            "bias_reason": bias_reason,
            "participants": participants
        }

    def get_bias_score_modifier(self, direction: str) -> Tuple[int, str]:
        """
        Returns conviction score adjustments (-15 to +15 pts) based on macro FII positioning.
        """
        if not self.data or "bias" not in self.data:
            return 0, "No participant data"

        bias = self.data["bias"]
        is_call = direction.upper() in ["BUY_CALL", "CE", "CALL"]
        fii = self.data.get("participants", {}).get("FII", {})
        fii_long_pct = fii.get("fut_long_pct", 50.0)

        if is_call:
            if bias in ["BULLISH", "MILD_BULLISH"]:
                return 10, f"FII Bullish Tailwinds ({fii_long_pct:.1f}% Long)"
            elif bias == "OVERSOLD_BOUNCE":
                return 15, f"FII Extreme Short Squeeze Potential ({fii_long_pct:.1f}% Long)"
            elif bias == "BEARISH":
                return -10, f"FII Heavy Short Headwinds ({fii_long_pct:.1f}% Long)"
            elif bias == "OVERBOUGHT_CORRECTION":
                return -10, f"FII Crowded Long Danger ({fii_long_pct:.1f}% Long)"
            return 0, "Neutral FII Positioning"
        else:
            # PE trades
            if bias in ["BEARISH", "MILD_BEARISH"]:
                return 10, f"FII Bearish Institutional Alignment ({fii_long_pct:.1f}% Long)"
            elif bias == "OVERBOUGHT_CORRECTION":
                return 15, f"FII Long Unwinding Tailwinds ({fii_long_pct:.1f}% Long)"
            elif bias in ["BULLISH", "OVERSOLD_BOUNCE"]:
                return -10, f"FII Bullish Headwinds ({fii_long_pct:.1f}% Long)"
            return 0, "Neutral FII Positioning"
