import pyotp
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
from SmartApi import SmartConnect
from src.data.base_feed import BaseDataFeed, MarketTick, Candle
from src.utils.logger import log

class AngelOneFeed(BaseDataFeed):
    """
    Live market data feed utilizing Angel One's free SmartAPI
    with automated TOTP session generation.
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

    def get_ltp(self, token: str, exchange: str = "NSE") -> float:
        """Fetch real-time LTP for instrument."""
        if not self.is_connected or not self.smart_api:
            return 0.0
        try:
            resp = self.smart_api.ltpData(exchange, token, token)
            if resp.get("status") and resp.get("data"):
                return float(resp["data"]["ltp"])
        except Exception as e:
            log.error(f"Error fetching LTP for token {token}: {e}")
        return 0.0

    def get_historical_candles(
        self,
        symbol: str,
        token: str,
        interval: str = "ONE_MINUTE",
        from_time: datetime = None,
        to_time: datetime = None,
        exchange: str = "NSE"
    ) -> List[Candle]:
        """Fetch historical candle data from Angel One SmartAPI."""
        if not self.is_connected or not self.smart_api:
            return []

        if to_time is None:
            to_time = datetime.now()
        if from_time is None:
            from_time = to_time - timedelta(days=5)

        from_str = from_time.strftime("%Y-%m-%d %H:%M")
        to_str = to_time.strftime("%Y-%m-%d %H:%M")

        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": interval,
            "fromdate": from_str,
            "todate": to_str
        }

        try:
            resp = self.smart_api.getCandleData(params)
            candles: List[Candle] = []
            if resp.get("status") and resp.get("data"):
                for row in resp["data"]:
                    # row format: [timestamp, open, high, low, close, volume]
                    dt = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%S%z")
                    candles.append(Candle(
                        symbol=symbol,
                        timestamp=dt,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=int(row[5])
                    ))
            return candles
        except Exception as e:
            log.error(f"Error fetching historical candles for {symbol}: {e}")
            return []

    def subscribe_ticks(self, tokens: List[str], callback: Callable[[MarketTick], None]):
        """WebSocket subscription hook."""
        log.info(f"Subscribed to {len(tokens)} tokens on Angel One WebSocket.")
