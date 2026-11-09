"""
DhanHQ Market Data Feed Connector for GravityOptions.
Integrates DhanHQ Python SDK (v2.3+) for ultra-low latency candles,
live market quotes, and native unified Option Chain with precomputed Greeks.
"""
import time
import os
from datetime import datetime, date, timedelta
from typing import Callable, Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np

try:
    from dhanhq import dhanhq, DhanContext
    DHAN_AVAILABLE = True
except (ImportError, SyntaxError, Exception):
    DHAN_AVAILABLE = False

from src.data.base_feed import BaseDataFeed, Candle, MarketTick
from src.utils.logger import log
from src.utils.time_utils import get_now_ist

# Standard Dhan Security IDs for major Indian Indices
DHAN_INDEX_MAP = {
    "NIFTY": {"security_id": "13", "exchange_segment": "IDX_I", "instrument_type": "INDEX", "yf_ticker": "^NSEI"},
    "NIFTY 50": {"security_id": "13", "exchange_segment": "IDX_I", "instrument_type": "INDEX", "yf_ticker": "^NSEI"},
    "BANKNIFTY": {"security_id": "25", "exchange_segment": "IDX_I", "instrument_type": "INDEX", "yf_ticker": "^NSEBANK"},
    "NIFTY BANK": {"security_id": "25", "exchange_segment": "IDX_I", "instrument_type": "INDEX", "yf_ticker": "^NSEBANK"},
    "FINNIFTY": {"security_id": "27", "exchange_segment": "IDX_I", "instrument_type": "INDEX", "yf_ticker": "NIFTY_FIN_SERVICE.NS"},
    "SENSEX": {"security_id": "51", "exchange_segment": "BSE_EQ", "instrument_type": "INDEX", "yf_ticker": "^BSESN"},
}

class DhanFeed(BaseDataFeed):
    """
    Data feed implementation powered by DhanHQ API.
    Provides:
      - 5-minute and 15-minute intraday candles with OI
      - Native unified option chain (/v2/optionchain) with Greeks (Delta, Theta, Gamma, IV)
      - Live quote snapshots without aggressive rate limits
      - Automatic secondary fallback to yfinance during market close/holidays
    """

    def __init__(
        self,
        client_id: str,
        access_token: str,
        cache_ttl: float = 2.0,
        use_yfinance_fallback: bool = True
    ):
        self.client_id = str(client_id).strip()
        self.access_token = str(access_token).strip()
        self.cache_ttl = cache_ttl
        self.use_yfinance_fallback = use_yfinance_fallback

        self.dhan: Optional[Any] = None
        self.context: Optional[Any] = None
        self.is_connected: bool = False
        self._cached_ltp: Dict[str, float] = {}
        self._last_quote_time: Dict[str, float] = {}

    def connect(self) -> bool:
        """Initialize DhanHQ connection and authenticate."""
        if not DHAN_AVAILABLE:
            log.error("❌ 'dhanhq' library is not installed. Run: pip install dhanhq")
            return False

        if not self.client_id or not self.access_token or self.client_id == "YOUR_DHAN_CLIENT_ID":
            log.warning("⚠️ Dhan client_id or access_token not configured. Running in unauthenticated / fallback mode.")
            return False

        try:
            self.context = DhanContext(self.client_id, self.access_token)
            self.dhan = dhanhq(self.context)

            # Test connection with fund limits query
            fund_resp = self.dhan.get_fund_limits()
            if isinstance(fund_resp, dict) and fund_resp.get("status", "").lower() in ["success", "ok"]:
                avail_cash = fund_resp.get("data", {}).get("availMargin", 0.0)
                log.info(f"✅ [DhanFeed] Connected successfully to DhanHQ API! Available Margin: ₹{avail_cash:,.2f}")
                self.is_connected = True
                return True
            elif isinstance(fund_resp, dict) and "data" in fund_resp:
                log.info(f"✅ [DhanFeed] Connected to DhanHQ API for Client: {self.client_id}")
                self.is_connected = True
                return True
            else:
                err_msg = fund_resp.get("remarks", fund_resp.get("message", str(fund_resp))) if isinstance(fund_resp, dict) else str(fund_resp)
                log.error(f"❌ [DhanFeed] Dhan authentication failed: {err_msg}")
                self.is_connected = False
                return False

        except Exception as e:
            log.error(f"❌ [DhanFeed] Exception during DhanHQ connection: {e}")
            self.is_connected = False
            return False

    def disconnect(self):
        """Cleanly close connection."""
        self.is_connected = False
        self.dhan = None
        log.info("🔌 [DhanFeed] Disconnected.")

    def subscribe_ticks(self, tokens: List[str], callback: Callable[[MarketTick], None]):
        """Placeholder for websocket market feed."""
        pass

    def get_ltp(self, token: str, exchange: str = "NSE") -> float:
        """Fetch latest single price with TTL caching."""
        sym = token.upper().strip()
        now_ts = time.time()

        if sym in self._cached_ltp and (now_ts - self._last_quote_time.get(sym, 0.0) < self.cache_ttl):
            return self._cached_ltp[sym]

        if not self.is_connected or not self.dhan:
            return self._cached_ltp.get(sym, 0.0)

        try:
            sec_id = self._resolve_security_id(sym)
            seg = "IDX_I" if sym in DHAN_INDEX_MAP else ("NSE_FNO" if exchange in ["NFO", "NSE_FNO"] else "NSE_EQ")
            
            resp = self.dhan.quote_data({seg: [sec_id]})
            if isinstance(resp, dict) and resp.get("status", "").lower() == "success":
                data = resp.get("data", {})
                item = data.get(sec_id, {}) or data.get(str(sec_id), {})
                ltp = float(item.get("last_price", 0.0) or item.get("ltp", 0.0))
                if ltp > 0:
                    self._cached_ltp[sym] = ltp
                    self._last_quote_time[sym] = now_ts
                    return ltp
        except Exception as e:
            log.debug(f"[DhanFeed] Error querying quote for {sym}: {e}")

        return self._cached_ltp.get(sym, 0.0)

    def get_historical_candles(
        self,
        symbol: str,
        token: str,
        interval: str = "FIVE_MINUTE",
        from_time: datetime = None,
        to_time: datetime = None,
        exchange: str = "NSE",
        count: int = 50,
        **kwargs
    ) -> List[Candle]:
        """
        Fetch intraday candles from DhanHQ.
        Supports 5-minute and 15-minute intervals. Falls back to yfinance if market is closed or on error.
        """
        now = get_now_ist()
        if not to_time:
            to_time = now
        if not from_time:
            from_time = to_time - timedelta(days=5)

        dhan_interval = 5 if "FIVE" in interval.upper() or interval == "5m" else 15

        if self.is_connected and self.dhan:
            try:
                sym_upper = symbol.upper().strip()
                idx_info = DHAN_INDEX_MAP.get(sym_upper)
                if idx_info:
                    sec_id = idx_info["security_id"]
                    seg = idx_info["exchange_segment"]
                    inst = idx_info["instrument_type"]
                else:
                    sec_id = self._resolve_security_id(sym_upper)
                    seg = "NSE_FNO" if exchange in ["NFO", "NSE_FNO"] else "NSE_EQ"
                    inst = "EQUITY"

                resp = self.dhan.intraday_minute_data(
                    security_id=sec_id,
                    exchange_segment=seg,
                    instrument_type=inst,
                    from_date=from_time.strftime("%Y-%m-%d"),
                    to_date=to_time.strftime("%Y-%m-%d"),
                    interval=dhan_interval,
                    oi=True
                )

                if isinstance(resp, dict) and resp.get("status", "").lower() == "success":
                    data = resp.get("data", {})
                    opens = data.get("open", [])
                    highs = data.get("high", [])
                    lows = data.get("low", [])
                    closes = data.get("close", [])
                    volumes = data.get("volume", [])
                    ois = data.get("oi", [])
                    epochs = data.get("start_time", []) or data.get("timestamp", [])

                    candles = []
                    for i in range(len(opens)):
                        ts = datetime.fromtimestamp(epochs[i]) if i < len(epochs) else (from_time + timedelta(minutes=i * dhan_interval))
                        candles.append(Candle(
                            symbol=symbol,
                            timestamp=ts,
                            open=float(opens[i]),
                            high=float(highs[i]),
                            low=float(lows[i]),
                            close=float(closes[i]),
                            volume=int(volumes[i]) if i < len(volumes) else 0,
                            oi=int(ois[i]) if i < len(ois) else 0
                        ))

                    if candles:
                        return candles[-count:]

            except Exception as e:
                log.warning(f"⚠️ [DhanFeed] Error querying intraday candles for {symbol}: {e}")

        # Fallback to high-reliability secondary feed (yfinance)
        if self.use_yfinance_fallback:
            return self._fetch_yfinance_candles(symbol, interval=f"{dhan_interval}m", count=count)

        return []

    def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Native unified Dhan Option Chain endpoint (/v2/optionchain).
        Fetches all strikes, volume, open interest, and precomputed Greeks (Delta, Theta, Gamma, IV).
        """
        if not self.is_connected or not self.dhan:
            return {}

        sym_upper = symbol.upper().strip()
        idx_info = DHAN_INDEX_MAP.get(sym_upper)
        if not idx_info:
            return {}

        sec_id = idx_info["security_id"]
        seg = idx_info["exchange_segment"]

        # Default expiry: nearest Thursday if not provided
        if not expiry:
            today = date.today()
            days_ahead = (3 - today.weekday()) % 7 # Thursday is weekday 3
            if days_ahead == 0 and datetime.now().hour >= 15:
                days_ahead = 7
            next_thu = today + timedelta(days=days_ahead)
            expiry = next_thu.strftime("%Y-%m-%d")

        try:
            resp = self.dhan.option_chain(
                under_security_id=sec_id,
                under_exchange_segment=seg,
                expiry=expiry
            )
            if isinstance(resp, dict) and resp.get("status", "").lower() == "success":
                return resp.get("data", {})
        except Exception as e:
            log.warning(f"⚠️ [DhanFeed] Error querying option chain for {symbol}: {e}")

        return {}

    def _resolve_security_id(self, symbol: str) -> str:
        """Resolve security ID from built-in index map or token."""
        sym_upper = symbol.upper().strip()
        if sym_upper in DHAN_INDEX_MAP:
            return DHAN_INDEX_MAP[sym_upper]["security_id"]
        return symbol

    def _fetch_yfinance_candles(self, symbol: str, interval: str = "5m", count: int = 50) -> List[Candle]:
        """Secondary fallback candle provider using yfinance."""
        import yfinance as yf
        sym_upper = symbol.upper().strip()
        ticker_map = {
            "NIFTY": "^NSEI",
            "NIFTY 50": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "NIFTY BANK": "^NSEBANK",
            "SENSEX": "^BSESN",
            "FINNIFTY": "NIFTY_FIN_SERVICE.NS"
        }
        yf_symbol = ticker_map.get(sym_upper, f"{sym_upper}.NS")

        try:
            df = yf.download(
                yf_symbol,
                period="5d",
                interval=interval,
                progress=False,
                auto_adjust=False
            )
            if df.empty:
                return []

            if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
                df.columns = [col[0].lower() for col in df.columns]
            else:
                df.columns = [col.lower() for col in df.columns]

            candles = []
            for idx, row in df.iterrows():
                ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
                candles.append(Candle(
                    symbol=symbol,
                    timestamp=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row.get("volume", 0) or 0)
                ))

            if candles:
                log.debug(f"ℹ️ [DhanFeed] Fetched {len(candles)} real candles for {symbol} via secondary feed.")
                return candles[-count:]

        except Exception as e:
            log.warning(f"⚠️ [DhanFeed] Secondary feed candle fetch failed for {symbol}: {e}")

        return []
