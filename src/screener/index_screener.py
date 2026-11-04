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
        if len(candles) < 5:
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

        # Intraday VWAP: Calculate strictly on today's session (or latest day in dataset)
        df["date_only"] = df["timestamp"].apply(lambda x: x.date() if hasattr(x, "date") else x)
        latest_date = df["date_only"].iloc[-1]
        today_mask = df["date_only"] == latest_date

        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        df["vwap"] = typical_price # Default baseline

        today_indices = df[today_mask].index
        today_vol = df.loc[today_indices, "volume"]
        today_tp = typical_price.loc[today_indices]

        if today_vol.sum() > 0:
            cum_vol = today_vol.cumsum()
            cum_pv = (today_tp * today_vol).cumsum()
            df.loc[today_indices, "vwap"] = cum_pv / cum_vol.replace(0, np.nan)
        else:
            # Fallback for cash index with 0 reported volume: expanding typical price mean
            df.loc[today_indices, "vwap"] = today_tp.expanding().mean()

        df["vwap"] = df["vwap"].ffill().bfill()

        # Average True Range (ATR)
        high_low = df["high"] - df["low"]
        high_prev_close = (df["high"] - df["close"].shift(1)).abs()
        low_prev_close = (df["low"] - df["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        df["atr"] = true_range.rolling(min(self.atr_period, len(df))).mean()

        return df

    def evaluate_orb_setup(
        self,
        symbol: str,
        candles: List[Candle],
        strike_step: int = 50
    ) -> Optional[IndexSignal]:
        """
        Check for 15-minute Opening Range Breakout strictly using TODAY's opening range
        with VWAP and EMA confirmation.
        """
        df = self.calculate_indicators(candles)
        if df.empty or len(df) < 5:
            return None

        # Filter strictly for today's session
        latest_date = df["date_only"].iloc[-1]
        today_df = df[df["date_only"] == latest_date].copy()

        # Must have completed the 15-minute opening range (3 x 5m bars) plus at least 1 active bar
        if len(today_df) < 4:
            return None

        # Morning Opening Range: First 3 bars of 5m (09:15 - 09:30 IST)
        orb_bars = today_df.iloc[0:3]
        orb_high = orb_bars["high"].max()
        orb_low = orb_bars["low"].min()

        last_row = today_df.iloc[-1]
        prev_row = today_df.iloc[-2]

        current_close = last_row["close"]
        current_open = last_row["open"]
        prev_close = prev_row["close"]
        vwap = last_row["vwap"]
        ema_f = last_row["ema_fast"]
        ema_s = last_row["ema_slow"]

        # Bullish Breakout: Decisive green candle closing above today's ORB High, above VWAP, EMA Bullish
        if (current_close > orb_high and prev_close <= orb_high and 
            current_close > current_open and current_close > vwap and ema_f > ema_s):
            
            # Select ATM / slightly ITM Call
            atm_strike = round(round(current_close / strike_step) * strike_step, 1)
            reason = f"Bullish Breakout: Broke Today's ORB High ₹{orb_high:.1f} | Close > VWAP ₹{vwap:.1f} | EMA Bullish"
            return IndexSignal(
                symbol=symbol,
                direction="BUY_CALL",
                option_type="CE",
                spot_price=current_close,
                trigger_reason=reason,
                target_strike=atm_strike,
                delta_estimate=0.55
            )

        # Bearish Breakdown: Decisive red candle closing below today's ORB Low, below VWAP, EMA Bearish
        elif (current_close < orb_low and prev_close >= orb_low and 
              current_close < current_open and current_close < vwap and ema_f < ema_s):
            
            # Select ATM / slightly ITM Put
            atm_strike = round(round(current_close / strike_step) * strike_step, 1)
            reason = f"Bearish Breakdown: Broke Today's ORB Low ₹{orb_low:.1f} | Close < VWAP ₹{vwap:.1f} | EMA Bearish"
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
