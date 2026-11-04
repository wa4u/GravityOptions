from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from src.data.base_feed import Candle
from src.utils.logger import log

@dataclass
class IndexSignal:
    symbol: str
    direction: str       # "BUY_CALL" or "BUY_PUT"
    option_type: str     # "CE" or "PE"
    spot_price: float
    trigger_reason: str
    target_strike: float
    delta_estimate: float

class IndexScreener:
    """
    Screens Indian Indices (NIFTY, BANKNIFTY, SENSEX, FINNIFTY)
    using 15-min Opening Range Breakout (ORB) + VWAP Slope + EMA Trend.
    """
    def __init__(self, ema_fast: int = 9, ema_slow: int = 21, atr_period: int = 14):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period

    def calculate_indicators(self, candles: List[Candle]) -> pd.DataFrame:
        if len(candles) < 20:
            return pd.DataFrame()

        df = pd.DataFrame([{
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        } for c in candles])

        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # Exponential Moving Averages
        df["ema_fast"] = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.ema_slow, adjust=False).mean()

        # Cumulative VWAP
        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        df["cum_vol"] = df["volume"].cumsum()
        df["cum_pv"] = (typical_price * df["volume"]).cumsum()
        df["vwap"] = df["cum_pv"] / df["cum_vol"].replace(0, np.nan)

        # Average True Range (ATR)
        high_low = df["high"] - df["low"]
        high_prev_close = (df["high"] - df["close"].shift(1)).abs()
        low_prev_close = (df["low"] - df["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        df["atr"] = true_range.rolling(self.atr_period).mean()

        return df

    def evaluate_orb_setup(
        self,
        symbol: str,
        candles: List[Candle],
        strike_step: int = 50
    ) -> Optional[IndexSignal]:
        """
        Check for 15-minute Opening Range Breakout with VWAP and EMA confirmation.
        """
        df = self.calculate_indicators(candles)
        if df.empty or len(df) < 5:
            return None

        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        # Morning Opening Range: First 15-minute range (first 3 bars of 5m or 2 bars of 15m)
        orb_bars = 3 if len(df) >= 6 else 2
        orb_high = df.iloc[0:orb_bars]["high"].max()
        orb_low = df.iloc[0:orb_bars]["low"].min()

        current_close = last_row["close"]
        vwap = last_row["vwap"]
        ema_f = last_row["ema_fast"]
        ema_s = last_row["ema_slow"]

        # Bullish Breakout: Price crosses above ORB High, above VWAP, EMA fast > slow
        if (current_close > orb_high and prev_row["close"] <= orb_high and 
            current_close > vwap and ema_f > ema_s):
            
            # Select ATM / slightly ITM Call
            atm_strike = round(round(current_close / strike_step) * strike_step, 1)
            reason = f"Bullish Breakout: Broke ORB High ₹{orb_high:.1f} | Close > VWAP ₹{vwap:.1f} | EMA Bullish"
            return IndexSignal(
                symbol=symbol,
                direction="BUY_CALL",
                option_type="CE",
                spot_price=current_close,
                trigger_reason=reason,
                target_strike=atm_strike,
                delta_estimate=0.55
            )

        # Bearish Breakdown: Price crosses below ORB Low, below VWAP, EMA fast < slow
        elif (current_close < orb_low and prev_row["close"] >= orb_low and 
              current_close < vwap and ema_f < ema_s):
            
            # Select ATM / slightly ITM Put
            atm_strike = round(round(current_close / strike_step) * strike_step, 1)
            reason = f"Bearish Breakdown: Broke ORB Low ₹{orb_low:.1f} | Close < VWAP ₹{vwap:.1f} | EMA Bearish"
            return IndexSignal(
                symbol=symbol,
                direction="BUY_PUT",
                option_type="PE",
                spot_price=current_close,
                trigger_reason=reason,
                target_strike=atm_strike,
                delta_estimate=-0.55
            )

        return None
