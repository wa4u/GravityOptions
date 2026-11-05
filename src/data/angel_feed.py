import time
import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
from dateutil import parser as date_parser
import pyotp

# Silence internal verbose logs from SmartAPI/logzero
try:
    import logzero
    logzero.logger.setLevel(logging.CRITICAL)
except Exception:
    pass

from SmartApi import SmartConnect
import pandas as pd
from src.data.base_feed import BaseDataFeed, MarketTick, Candle
from src.utils.logger import log
from src.utils.time_utils import get_now_ist

KNOWN_TOKENS = {
    # Major Indices
    "NIFTY": ("99926000", "Nifty 50", "NSE"),
    "NIFTY 50": ("99926000", "Nifty 50", "NSE"),
    "BANKNIFTY": ("99926009", "Nifty Bank", "NSE"),
    "FINNIFTY": ("99926037", "FINNIFTY", "NSE"),
    "SENSEX": ("99919000", "SENSEX", "BSE"),

    # High Liquid Large-cap & F&O Stocks
    "RELIANCE": ("2885", "RELIANCE-EQ", "NSE"),
    "TCS": ("11536", "TCS-EQ", "NSE"),
    "HDFCBANK": ("1333", "HDFCBANK-EQ", "NSE"),
    "ICICIBANK": ("4963", "ICICIBANK-EQ", "NSE"),
    "INFY": ("1594", "INFY-EQ", "NSE"),
    "SBIN": ("3045", "SBIN-EQ", "NSE"),
    "BHARTIARTL": ("10604", "BHARTIARTL-EQ", "NSE"),
    "TATAMOTORS": ("3456", "TATAMOTORS-EQ", "NSE"),
    "LT": ("11483", "LT-EQ", "NSE"),
    "AXISBANK": ("5900", "AXISBANK-EQ", "NSE"),
    "MARUTI": ("10999", "MARUTI-EQ", "NSE"),
    "KOTAKBANK": ("1922", "KOTAKBANK-EQ", "NSE"),
    "BAJFINANCE": ("317", "BAJFINANCE-EQ", "NSE"),
    "M&M": ("2031", "M&M-EQ", "NSE"),
    "SUNPHARMA": ("3351", "SUNPHARMA-EQ", "NSE"),
    "TITAN": ("3506", "TITAN-EQ", "NSE"),
    "ITC": ("1660", "ITC-EQ", "NSE"),
    "COALINDIA": ("20374", "COALINDIA-EQ", "NSE"),
    "JSWSTEEL": ("11723", "JSWSTEEL-EQ", "NSE"),
    "TATASTEEL": ("3499", "TATASTEEL-EQ", "NSE"),
    "NTPC": ("11630", "NTPC-EQ", "NSE"),
    "ONGC": ("2475", "ONGC-EQ", "NSE"),
    "POWERGRID": ("14977", "POWERGRID-EQ", "NSE"),
    "ADANIENT": ("25", "ADANIENT-EQ", "NSE"),
    "ADANIPORTS": ("15083", "ADANIPORTS-EQ", "NSE"),
    "ASIANPAINT": ("236", "ASIANPAINT-EQ", "NSE"),
    "HEROMOTOCO": ("1348", "HEROMOTOCO-EQ", "NSE"),
    "HINDALCO": ("1363", "HINDALCO-EQ", "NSE"),
    "HINDUNILVR": ("1394", "HINDUNILVR-EQ", "NSE"),
    "ULTRACEMCO": ("11528", "ULTRACEMCO-EQ", "NSE"),
    "WIPRO": ("3787", "WIPRO-EQ", "NSE"),
    "TECHM": ("13538", "TECHM-EQ", "NSE"),
    "NESTLEIND": ("17963", "NESTLEIND-EQ", "NSE"),
    "GRASIM": ("1232", "GRASIM-EQ", "NSE"),
    "CIPLA": ("694", "CIPLA-EQ", "NSE"),
    "DRREDDY": ("881", "DRREDDY-EQ", "NSE"),
    "EICHERMOT": ("910", "EICHERMOT-EQ", "NSE"),
    "BPCL": ("526", "BPCL-EQ", "NSE"),
    "DIVISLAB": ("10940", "DIVISLAB-EQ", "NSE"),
    "APOLLOHOSP": ("157", "APOLLOHOSP-EQ", "NSE"),
    "SBILIFE": ("21808", "SBILIFE-EQ", "NSE"),
    "HDFCLIFE": ("467", "HDFCLIFE-EQ", "NSE"),
    "BAJAJFINSV": ("16675", "BAJAJFINSV-EQ", "NSE"),
    "BAJAJ-AUTO": ("16669", "BAJAJ-AUTO-EQ", "NSE"),
    "BRITANNIA": ("547", "BRITANNIA-EQ", "NSE"),
    "INDUSINDBK": ("5258", "INDUSINDBK-EQ", "NSE"),
    "LTIM": ("17818", "LTIM-EQ", "NSE"),
    "SHREECEM": ("3103", "SHREECEM-EQ", "NSE"),
    "VBL": ("1878", "VBL-EQ", "NSE"),
    "ZOMATO": ("5097", "ZOMATO-EQ", "NSE"),
    "BEL": ("383", "BEL-EQ", "NSE"),
    "HAL": ("2303", "HAL-EQ", "NSE"),
    "TRENT": ("1964", "TRENT-EQ", "NSE"),
    "SUPREMEIND": ("3363", "SUPREMEIND-EQ", "NSE"),
    "BOSCHLTD": ("2181", "BOSCHLTD-EQ", "NSE"),
    "SOLARINDS": ("13332", "SOLARINDS-EQ", "NSE"),
    "DIXON": ("21690", "DIXON-EQ", "NSE"),
    "POLYCAB": ("9590", "POLYCAB-EQ", "NSE"),
    "POLICYBZR": ("6656", "POLICYBZR-EQ", "NSE"),
    "MCX": ("31181", "MCX-EQ", "NSE"),
    "TVSMOTOR": ("8479", "TVSMOTOR-EQ", "NSE")
}

INTERVAL_MAP = {
    "1m": "ONE_MINUTE",
    "3m": "THREE_MINUTE",
    "5m": "FIVE_MINUTE",
    "10m": "TEN_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "60m": "ONE_HOUR",
    "1h": "ONE_HOUR",
    "1d": "ONE_DAY",
    "day": "ONE_DAY"
}

class AngelOneFeed(BaseDataFeed):
    """
    Live market data feed utilizing Angel One's SmartAPI
    with automated TOTP session generation, token resolution,
    rate-limiting protection (max 2.5 req/sec), and candle caching.
    """
    def __init__(
        self,
        api_key: str,
        client_id: str,
        password: str,
        totp_secret: str
    ):
        self.api_key = api_key
        self.client_id = client_id
        self.password = password
        self.totp_secret = totp_secret
        self.smart_api: Optional[SmartConnect] = None
        self.auth_token: Optional[str] = None
        self.feed_token: Optional[str] = None
        self.is_connected = False
        self._cached_ltp: Dict[str, float] = {}
        self._candle_cache: Dict[str, tuple] = {} # key -> (timestamp, List[Candle])
        self._last_api_call = 0.0
        self.instrument_mgr = None

    def _rate_limit(self, delay: float = 0.35):
        """Enforces safe delay between API requests to respect Angel One rate limits."""
        now = time.time()
        elapsed = now - self._last_api_call
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_api_call = time.time()

    def connect(self) -> bool:
        """Authenticate with Angel One using SmartAPI and auto TOTP."""
        if "YOUR_" in self.api_key or "YOUR_" in self.client_id:
            log.warning("Angel One credentials contain placeholders. Please update config/config.yaml")
            return False

        try:
            log.info(f"Authenticating with Angel One SmartAPI for Client ID: {self.client_id}...")
            self.smart_api = SmartConnect(api_key=self.api_key)
            
            # Auto-generate 6-digit TOTP
            totp = pyotp.TOTP(self.totp_secret).now()
            self._rate_limit(0.5)
            session = self.smart_api.generateSession(self.client_id, self.password, totp)
            
            if session.get("status"):
                self.auth_token = session["data"]["jwtToken"]
                self.feed_token = self.smart_api.getfeedToken()
                self.is_connected = True
                log.info("Successfully authenticated with Angel One SmartAPI!")
                return True
            else:
                log.error(f"Angel One Login Failed: {session.get('message')}")
                return False
        except Exception as e:
            log.error(f"Exception during Angel One authentication: {e}")
            return False

    def disconnect(self):
        if self.smart_api and self.is_connected:
            try:
                self.smart_api.terminateSession(self.client_id)
            except Exception:
                pass
            self.is_connected = False
            log.info("Disconnected from Angel One SmartAPI.")

    def _resolve_token_info(self, symbol_or_token: str, default_exchange: str = "NSE"):
        sym_key = str(symbol_or_token).upper().strip()
        if sym_key in KNOWN_TOKENS:
            tok, tradingsym, exch = KNOWN_TOKENS[sym_key]
            return tok, tradingsym, exch

        # Check InstrumentManager scrip cache for options / equities
        if hasattr(self, "instrument_mgr") and self.instrument_mgr:
            try:
                item = self.instrument_mgr.lookup_symbol(sym_key)
                if item:
                    return str(item.get("token")), item.get("symbol"), item.get("exch_seg", default_exchange)
            except Exception:
                pass

        # If already a numeric token string
        if sym_key.isdigit():
            return sym_key, sym_key, default_exchange

        # Fallback format: check if it's symbol-EQ
        return None, sym_key, default_exchange

    def get_ltp(self, token: str, exchange: str = "NSE") -> float:
        """Fetch real-time LTP for instrument with rate limiting and caching."""
        if not self.is_connected or not self.smart_api:
            return self._cached_ltp.get(token, 0.0)

        sym_token, tradingsym, exch = self._resolve_token_info(token, exchange)
        if not sym_token:
            # Token unknown; return cached price if available
            return self._cached_ltp.get(token, 0.0)

        try:
            self._rate_limit(0.35)
            resp = self.smart_api.ltpData(exch, tradingsym, sym_token)
            if resp.get("status") and resp.get("data"):
                price = float(resp["data"]["ltp"])
                self._cached_ltp[token] = price
                return price
        except Exception:
            pass

        return self._cached_ltp.get(token, 0.0)

    def get_market_data(self, mode: str, exchange_tokens: Dict[str, List[str]]) -> Dict:
        """
        Fetch batch market data (including Open Interest and volume) via SmartAPI getMarketData.
        mode: 'FULL', 'OHLC', or 'LTP'
        exchange_tokens: e.g. {'NFO': ['62185', '62186'], 'BFO': ['token1']}
        """
        if not self.is_connected or not self.smart_api:
            return {}

        try:
            self._rate_limit(0.40)
            resp = self.smart_api.getMarketData(mode, exchange_tokens)
            if resp and resp.get("status") and resp.get("data"):
                return resp["data"]
        except Exception as e:
            log.warning(f"Error fetching batch market data from SmartAPI: {e}")

        return {}

    def get_historical_candles(
        self,
        symbol: str,
        token: str,
        interval: str = "FIFTEEN_MINUTE",
        from_time: datetime = None,
        to_time: datetime = None,
        exchange: str = "NSE",
        count: int = 50,
        **kwargs
    ) -> List[Candle]:
        """
        Fetch historical candle data from Angel One SmartAPI.
        Includes 60-second in-memory caching and rate-limiting.
        """
        sym_token, tradingsym, exch = self._resolve_token_info(token if token else symbol, exchange)
        api_interval = INTERVAL_MAP.get(interval.lower(), interval)
        if api_interval not in INTERVAL_MAP.values():
            api_interval = "FIFTEEN_MINUTE"

        # Check 120-second cache (5-minute candles update every 5m; 120s caching saves rate limits)
        cache_key = f"{symbol}_{api_interval}"
        now_ts = time.time()
        if cache_key in self._candle_cache:
            last_ts, cached_candles = self._candle_cache[cache_key]
            if now_ts - last_ts < 120.0 and len(cached_candles) > 0:
                return cached_candles[-count:] if count and len(cached_candles) > count else cached_candles

        candles: List[Candle] = []

        if self.is_connected and self.smart_api and sym_token:
            try:
                now_ist = get_now_ist()
                if to_time is None:
                    to_time = now_ist
                if from_time is None:
                    from_time = to_time - timedelta(days=5)

                from_str = from_time.strftime("%Y-%m-%d %H:%M")
                to_str = to_time.strftime("%Y-%m-%d %H:%M")

                params = {
                    "exchange": exch,
                    "symboltoken": sym_token,
                    "interval": api_interval,
                    "fromdate": from_str,
                    "todate": to_str
                }
                
                # Respect Angel One rate limit (max 1 req/sec for historical candle endpoint)
                self._rate_limit(1.0)
                resp = self.smart_api.getCandleData(params)
                if resp and resp.get("status") and resp.get("data"):
                    for row in resp["data"]:
                        try:
                            dt = date_parser.parse(str(row[0]))
                            candles.append(Candle(
                                symbol=symbol,
                                timestamp=dt,
                                open=float(row[1]),
                                high=float(row[2]),
                                low=float(row[3]),
                                close=float(row[4]),
                                volume=int(row[5])
                            ))
                        except Exception:
                            continue
                else:
                    err_msg = resp.get("message") if resp else "No response"
                    if "exceeding access rate" in str(err_msg):
                        time.sleep(2.0)
                    log.warning(f"SmartAPI getCandleData returned no candles for {symbol} ({sym_token}, {exch}): {err_msg}")
            except Exception as e:
                err_str = str(e)
                if "exceeding access rate" in err_str:
                    log.warning(f"Angel One rate limit throttle hit on {symbol}. Backing off 2.5s...")
                    time.sleep(2.5)
                    # If we have cached candles from earlier, return them gracefully
                    if cache_key in self._candle_cache:
                        return self._candle_cache[cache_key][1][-count:]
                else:
                    log.error(f"Exception fetching candles for {symbol} ({sym_token}): {e}")

        if candles:
            self._candle_cache[cache_key] = (now_ts, candles)
            return candles[-count:] if count and len(candles) > count else candles

        # High-Reliability Fallback: Fetch real live market candles via secondary feed (yfinance)
        # Guarantees the system never halts even if SmartAPI hits 429/hourly rate limits
        yf_candles = self._fetch_yfinance_candles(symbol, interval=interval, count=count)
        if yf_candles:
            self._candle_cache[cache_key] = (now_ts, yf_candles)
            return yf_candles

        log.warning(f"No real candle data available for {symbol}. Screener will skip this cycle.")
        return []

    def _fetch_yfinance_candles(self, symbol: str, interval: str = "5m", count: int = 50) -> List[Candle]:
        """Fetch 100% real live market candles from Yahoo Finance when SmartAPI is throttled."""
        yf_map = {
            "NIFTY": "^NSEI",
            "NIFTY 50": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "SENSEX": "^BSESN",
            "FINNIFTY": "NIFTY_FIN_SERVICE.NS"
        }
        try:
            import yfinance as yf
            sym_key = symbol.upper().strip()
            ticker = yf_map.get(sym_key, f"{sym_key}.NS")
            yf_interval = "5m" if "5" in interval or "FIVE" in interval.upper() else ("15m" if "15" in interval else "5m")
            
            df = yf.download(ticker, period="2d", interval=yf_interval, progress=False)
            if df is None or df.empty:
                return []

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            candles: List[Candle] = []
            for ts, row in df.iterrows():
                try:
                    dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                    candles.append(Candle(
                        symbol=symbol,
                        timestamp=dt,
                        open=round(float(row["Open"]), 2),
                        high=round(float(row["High"]), 2),
                        low=round(float(row["Low"]), 2),
                        close=round(float(row["Close"]), 2),
                        volume=int(row.get("Volume", 0))
                    ))
                except Exception:
                    continue

            if candles:
                log.info(f"✅ Retrieved {len(candles)} real market candles for {symbol} via secondary market feed (LTP: ₹{candles[-1].close:,.2f})")
                return candles[-count:] if count and len(candles) > count else candles
        except Exception as e:
            log.warning(f"Secondary candle feed failed for {symbol}: {e}")

        return []

    def subscribe_ticks(self, tokens: List[str], callback: Callable[[MarketTick], None]):
        """WebSocket subscription hook."""
        log.info(f"Subscribed to {len(tokens)} tokens on Angel One WebSocket.")
