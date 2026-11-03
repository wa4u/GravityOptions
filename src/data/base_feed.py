from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional

@dataclass
class MarketTick:
    token: str
    symbol: str
    ltp: float
    best_bid: float
    best_ask: float
    volume: int
    oi: int
    timestamp: datetime

@dataclass
class Candle:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int = 0

class BaseDataFeed(ABC):
    """Abstract base class for all real-time and replay market feeds."""
    
    @abstractmethod
    def connect(self) -> bool:
        """Establish connection with broker or data vendor."""
        pass

    @abstractmethod
    def disconnect(self):
        """Cleanly close feed socket/session."""
        pass

    @abstractmethod
    def subscribe_ticks(self, tokens: List[str], callback: Callable[[MarketTick], None]):
        """Subscribe to real-time ticks."""
        pass

    @abstractmethod
    def get_historical_candles(
        self,
        symbol: str,
        token: str,
        interval: str,
        from_time: datetime,
        to_time: datetime
    ) -> List[Candle]:
        """Fetch historical OHLCV candle data."""
        pass

    @abstractmethod
    def get_ltp(self, token: str, exchange: str = "NSE") -> float:
        """Fetch latest single price."""
        pass
