from datetime import datetime, timedelta
import random
from typing import Callable, Dict, List
from src.data.base_feed import BaseDataFeed, MarketTick, Candle
from src.utils.logger import log

class MockReplayFeed(BaseDataFeed):
    """
    Simulated market feed for testing strategies, risk manager,
    paper trading execution, and Telegram alerts offline or after-hours.
    """
    def __init__(self):
        self.is_connected = False
        self.cached_ltp: Dict[str, float] = {
            "NIFTY": 24200.0,
            "BANKNIFTY": 51500.0,
            "SENSEX": 79500.0,
            "FINNIFTY": 23800.0,
            "RELIANCE": 2980.0,
            "HDFCBANK": 1740.0,
            "ICICIBANK": 1280.0,
            "INFY": 1820.0,
            "SBIN": 840.0,
            "TATAMOTORS": 960.0
        }

    def connect(self) -> bool:
        self.is_connected = True
        log.info("🔌 Mock Replay Data Feed connected successfully (Offline Simulation Mode).")
        return True

    def disconnect(self):
        self.is_connected = False

    def get_ltp(self, token: str, exchange: str = "NSE") -> float:
        # Generate realistic gentle random walk
        base = self.cached_ltp.get(token, 200.0)
        drift = base * random.uniform(-0.001, 0.001)
        self.cached_ltp[token] = round(base + drift, 2)
        return self.cached_ltp[token]

    def set_ltp(self, token: str, price: float):
        self.cached_ltp[token] = price

    def get_historical_candles(
        self,
        symbol: str,
        token: str,
        interval: str = "15m",
        from_time: datetime = None,
        to_time: datetime = None,
        count: int = 50
    ) -> List[Candle]:
        """Generate realistic synthetic OHLCV candles with trend."""
        base_price = self.cached_ltp.get(symbol, 24000.0)
        candles: List[Candle] = []
        now = datetime.now() if to_time is None else to_time

        current = base_price
        for i in range(count):
            dt = now - timedelta(minutes=(count - i) * 15)
            change = current * random.uniform(-0.004, 0.006)
            c_open = current
            c_close = current + change
            c_high = max(c_open, c_close) + abs(current * random.uniform(0.0005, 0.002))
            c_low = min(c_open, c_close) - abs(current * random.uniform(0.0005, 0.002))
            vol = random.randint(50000, 300000)

            candles.append(Candle(
                symbol=symbol,
                timestamp=dt,
                open=round(c_open, 2),
                high=round(c_high, 2),
                low=round(c_low, 2),
                close=round(c_close, 2),
                volume=vol
            ))
            current = c_close

        return candles

    def subscribe_ticks(self, tokens: List[str], callback: Callable[[MarketTick], None]):
        pass
